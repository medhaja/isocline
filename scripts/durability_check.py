#!/usr/bin/env python3
"""Durable-execution checks against a LIVE Isocline stack (API + PostgreSQL + Redis + Celery worker + beat).

Unlike the unit/integration suites (SQLite, in-process dispatcher), these scenarios exercise the real queue, the real
beat schedule and real process failures. Process control is delegated to shell commands so the same script works
with Docker Compose or with locally started processes:

    python scripts/durability_check.py --base-url http://localhost:8000 \
        --kill-worker   "docker compose kill -s SIGKILL worker" \
        --start-worker  "docker compose up -d worker" \
        --stop-worker   "docker compose stop worker" \
        --restart-api   "docker compose restart api" \
        --restart-redis "docker compose restart redis" \
        --flush-redis   "docker compose exec -T redis redis-cli FLUSHALL"

Requires the deterministic local test provider (ISOCLINE_ENABLE_TEST_PROVIDER=true) and, for the saga scenario,
ISOCLINE_ALLOW_PRIVATE_NETWORK_HOSTS to include the host this script's mock server listens on (--mock-host).
Prints one line per scenario and exits non-zero if any scenario fails. Nothing here is simulated: a "worker crash" is
a SIGKILL of the worker process tree while a node is executing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

API = "/api/v1"


# ------------------------------------------------------------------ graph helpers
def node(id_, type_, key=None, **config):
    return {"id": id_, "key": key or id_, "type": type_, "name": id_, "position": {"x": 0, "y": 0}, "config": config}


def agent(id_, model="echo", prompt="Work on {{input.topic}}", **extra):
    return node(id_, "agent", model={"provider": "local_test", "model": model}, prompt=prompt, **extra)


def edge(s, t, sh=None):
    return {"id": f"e_{s}_{t}_{sh or ''}", "source": s, "target": t, "source_handle": sh}


def graph(nodes, edges, **settings):
    return {"schema_version": "1.0", "nodes": nodes, "edges": edges, "settings": settings}


# ------------------------------------------------------------------ client
class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.h = httpx.Client(base_url=self.base, timeout=30)
        email = f"durability-{uuid.uuid4().hex[:8]}@example.com"
        r = self.h.post(f"{API}/auth/register", json={"email": email, "password": "durability-check-pw", "name": "Durability"})
        if r.status_code == 403:
            sys.exit("Sign-up is closed on this installation: run with ISOCLINE_ALLOW_SIGNUP=true or on a fresh install.")
        r.raise_for_status()
        ws = r.json()["workspace_id"]
        csrf = {"X-CSRF-Token": self.h.cookies.get("isc_csrf")}
        tok = self.h.post(f"{API}/tokens", json={"name": "durability-check"}, headers=csrf)
        tok.raise_for_status()
        self.h.cookies.clear()
        self.h.headers["Authorization"] = f"Bearer {tok.json()['token']}"
        self.project = self.get(f"{API}/workspaces/{ws}/projects")[0]["id"]

    def get(self, url):
        r = self.h.get(url)
        r.raise_for_status()
        return r.json()

    def post(self, url, body=None, ok=(200, 201, 202)):
        for attempt in range(20):  # the API may be restarting
            try:
                r = self.h.post(url, json=body or {})
                break
            except httpx.TransportError:
                time.sleep(1)
        else:
            raise RuntimeError(f"API unreachable: {url}")
        if r.status_code not in ok:
            raise RuntimeError(f"POST {url} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def workflow(self, name, g):
        return self.post(f"{API}/projects/{self.project}/workflows", {"name": name, "graph": g})["id"]

    def run(self, wf, inp=None):
        return self.post(f"{API}/workflows/{wf}/run", {"input": inp or {"topic": "Acme Corp"}})["run_id"]

    def status(self, run_id):
        for _ in range(30):
            try:
                return self.get(f"{API}/runs/{run_id}")
            except httpx.TransportError:
                time.sleep(1)
        raise RuntimeError("API unreachable")

    def wait(self, run_id, statuses, timeout):
        end = time.time() + timeout
        while time.time() < end:
            r = self.status(run_id)
            if r["status"] in statuses:
                return r
            time.sleep(0.5)
        raise TimeoutError(f"run {run_id} did not reach {statuses} in {timeout}s (last: {r['status']})")

    def nodes(self, run_id):
        return {n["node_key"]: n for n in self.get(f"{API}/runs/{run_id}/nodes") if not n.get("scope")}


def sh(cmd):
    if cmd:
        subprocess.run(cmd, shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------ mock external service (sagas, callbacks)
class Mock:
    def __init__(self, host, port):
        self.calls: list[str] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def _do(self):
                n = int(self.headers.get("content-length") or 0)
                self.rfile.read(n)
                outer.calls.append(f"{self.command} {self.path}")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"id": self.path.strip("/")}).encode())
            do_GET = do_POST = do_DELETE = do_PUT = _do

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer((host, port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


# ------------------------------------------------------------------ scenarios
def s_sequential(c, a):
    wf = c.workflow("seq", graph([node("i", "input_text", key="inp", field="topic"), agent("a"), agent("b", prompt="{{a.output}}"),
                                   node("o", "output_text")], [edge("i", "a"), edge("a", "b"), edge("b", "o")]))
    r = c.wait(c.run(wf), {"completed", "failed"}, 60)
    assert r["status"] == "completed", r.get("error")
    assert r["llm_calls"] == 2
    return "2 agents in sequence completed; 2 model calls recorded"


def s_parallel(c, a):
    wf = c.workflow("par", graph([node("i", "input_text", key="inp", field="topic"), node("p", "parallel"),
                                   agent("x", "slow-3"), agent("y", "slow-3"), node("m", "merge", key="merge"), node("o", "output_json")],
                                  [edge("i", "p"), edge("p", "x"), edge("p", "y"), edge("x", "m"), edge("y", "m"), edge("m", "o")]))
    t0 = time.time()
    r = c.wait(c.run(wf), {"completed", "failed"}, 60)
    wall = time.time() - t0
    assert r["status"] == "completed", r.get("error")
    n = c.nodes(r["id"])
    overlap = n["x"]["started_at"] < n["y"]["finished_at"] and n["y"]["started_at"] < n["x"]["finished_at"]
    assert overlap, "branches did not overlap"
    return f"two 3 s branches overlapped in time; run wall clock {wall:.1f} s (serial would be >= 6 s)"


def s_worker_crash(c, a):
    wf = c.workflow("crash", graph([node("i", "input_text", key="inp", field="topic"), agent("first", "echo"),
                                     agent("long", "slow-12", prompt="{{first.output}}"), agent("last", "echo"), node("o", "output_text")],
                                    [edge("i", "first"), edge("first", "long"), edge("long", "last"), edge("last", "o")]))
    rid = c.run(wf)
    end = time.time() + 60
    while time.time() < end:
        n = c.nodes(rid)
        if n.get("long", {}).get("status") == "running":
            break
        time.sleep(0.3)
    else:
        raise AssertionError("node 'long' never started")
    sh(a.kill_worker)
    killed_at = time.time()
    time.sleep(2)
    sh(a.start_worker)
    r = c.wait(rid, {"completed", "failed"}, a.recovery_timeout)
    assert r["status"] == "completed", r.get("error")
    assert r["recovery_attempts"] >= 1, "sweeper did not record a recovery"
    first_runs = [x for x in c.get(f"{API}/runs/{rid}/nodes") if x["node_key"] == "first"]
    assert len(first_runs) == 1 and first_runs[0]["status"] == "completed", "completed upstream node was re-executed"
    return (f"worker SIGKILLed mid-node; recovered and completed {time.time() - killed_at:.0f} s later "
            f"(recovery_attempts={r['recovery_attempts']}); the completed upstream node was not re-executed")


def s_approval_restart(c, a):
    wf = c.workflow("approval", graph([node("i", "input_text", key="inp", field="topic"), agent("draft"),
                                        node("ok", "human_approval", key="review", title="Approve"), node("o", "output_text")],
                                       [edge("i", "draft"), edge("draft", "ok"), edge("ok", "o", "approved")]))
    rid = c.run(wf)
    c.wait(rid, {"waiting"}, 60)
    active = subprocess.run(a.active_tasks, shell=True, capture_output=True, text=True).stdout.strip() if a.active_tasks else ""
    sh(a.restart_api)
    sh(a.kill_worker)
    sh(a.restart_redis)
    time.sleep(3)
    sh(a.start_worker)
    time.sleep(3)
    assert c.status(rid)["status"] == "waiting"
    ap = c.get(f"{API}/runs/{rid}/approvals")[0]
    c.post(f"{API}/approvals/{ap['id']}/decide", {"decision": "approved"})
    r = c.wait(rid, {"completed", "failed"}, 90)
    assert r["status"] == "completed", r.get("error")
    extra = f"; worker active tasks while waiting: {active}" if active else ""
    return f"paused on approval, API + worker + Redis restarted, approved afterwards, run completed{extra}"


def s_timer_with_redis_loss(c, a):
    wf = c.workflow("timer", graph([node("i", "input_text", key="inp", field="topic"), node("t", "wait_timer", key="pause", duration_seconds=15),
                                     agent("after"), node("o", "output_text")], [edge("i", "t"), edge("t", "after"), edge("after", "o")]))
    rid = c.run(wf)
    c.wait(rid, {"waiting"}, 60)
    t0 = time.time()
    sh(a.flush_redis)  # every queued message and cached key is gone; durable state is in PostgreSQL
    r = c.wait(rid, {"completed", "failed"}, 120)
    assert r["status"] == "completed", r.get("error")
    return f"15 s timer survived a Redis FLUSHALL; resumed and completed {time.time() - t0:.0f} s after the flush"


def s_lost_queue_message(c, a):
    wf = c.workflow("lost", graph([node("i", "input_text", key="inp", field="topic"), agent("a"), node("o", "output_text")],
                                   [edge("i", "a"), edge("a", "o")]))
    sh(a.stop_worker)
    time.sleep(2)
    rid = c.run(wf)
    time.sleep(1)
    sh(a.flush_redis)  # the enqueued message is lost before any worker saw it
    sh(a.start_worker)
    r = c.wait(rid, {"completed", "failed"}, a.recovery_timeout)
    assert r["status"] == "completed", r.get("error")
    return "run enqueued, queue message destroyed before pickup; the sweeper re-enqueued it from PostgreSQL"


def s_callback(c, a):
    wf = c.workflow("callback", graph([node("i", "input_text", key="inp", field="topic"),
                                        node("w", "wait_webhook", key="hook", max_wait_seconds=300), node("o", "output_json", template="{{hook.output}}")],
                                       [edge("i", "w"), edge("w", "o")]))
    rid = c.run(wf)
    c.wait(rid, {"waiting"}, 60)
    ev = c.get(f"{API}/runs/{rid}/events.json")
    events = ev if isinstance(ev, list) else ev.get("events", [])
    path = next((e.get("data") or {}).get("callback_path") for e in events
                if e.get("type") == "NODE_WAITING" and (e.get("data") or {}).get("callback_path"))
    r1 = httpx.post(c.base + path, json={"approved_amount": 1200})
    r2 = httpx.post(c.base + path, json={"approved_amount": 9999})
    r = c.wait(rid, {"completed", "failed"}, 60)
    assert r["status"] == "completed", r.get("error")
    assert "1200" in json.dumps(r["output"]) and "9999" not in json.dumps(r["output"])
    return f"callback resumed the run (HTTP {r1.status_code}); a duplicate delivery was ignored (HTTP {r2.status_code})"


def s_rerun_from_node(c, a):
    wf = c.workflow("rerun", graph([node("i", "input_text", key="inp", field="topic"), agent("up"), agent("down", prompt="{{up.output}}"),
                                     node("o", "output_text")], [edge("i", "up"), edge("up", "down"), edge("down", "o")]))
    first = c.wait(c.run(wf), {"completed"}, 60)
    g = c.get(f"{API}/runs/{first['id']}")["graph_snapshot"]
    down_id = next(n["id"] for n in g["nodes"] if n["key"] == "down")
    child = c.post(f"{API}/runs/{first['id']}/replay", {"node_id": down_id})["run_id"]
    r = c.wait(child, {"completed", "failed"}, 60)
    assert r["status"] == "completed", r.get("error")
    assert r["llm_calls"] == 1, f"expected only 'down' to call the model, got {r['llm_calls']}"
    return "re-ran from 'down': upstream output reused, exactly 1 model call in the child run"


def s_checkpoint_resume(c, a):
    up = agent("up")
    up["harness"] = {"checkpoint": True}
    wf = c.workflow("checkpoint", graph([node("i", "input_text", key="inp", field="topic"), up, agent("boom", "fail"), node("o", "output_text")],
                                         [edge("i", "up"), edge("up", "boom"), edge("boom", "o")]))
    r = c.wait(c.run(wf), {"completed", "failed"}, 60)
    assert r["status"] == "failed"
    cps = c.get(f"{API}/runs/{r['id']}/harness")["checkpoints"]
    assert cps, "no checkpoint recorded"
    cp = next(x for x in cps if x["node_key"] == "up")
    child = c.post(f"{API}/runs/{r['id']}/resume", {"checkpoint_id": cp["id"]})["run_id"]
    rr = c.wait(child, {"completed", "failed"}, 60)
    nodes = c.get(f"{API}/runs/{child}/nodes")
    up_child = [n for n in nodes if n["node_key"] == "up"]
    reused = all(n.get("input_tokens", 0) == 0 and n.get("output_tokens", 0) == 0 for n in up_child)
    assert reused, "checkpointed node was executed again"
    return f"failed run resumed from checkpoint after 'up' ({len(cps)} checkpoint(s)); 'up' was restored, not re-executed (child: {rr['status']})"


def s_saga(c, a, mock_url):
    def step(id_, path):
        n = node(id_, "tool_http", key=id_, arguments={"method": "POST", "url": f"{mock_url}/{path}"})
        n["harness"] = {"compensation": {"tool": "http_request", "arguments": {"method": "DELETE", "url": f"{mock_url}/{path}"}}}
        n["contract"] = {"side_effects": "external_write"}
        return n
    wf = c.workflow("saga", graph([node("i", "input_text", key="inp", field="topic"), step("reserve", "reserve"),
                                    step("charge", "charge"), step("ship", "ship"), agent("fails", "fail"), node("o", "output_text")],
                                   [edge("i", "reserve"), edge("reserve", "charge"), edge("charge", "ship"), edge("ship", "fails"), edge("fails", "o")],
                                   compensation_enabled=True))
    r = c.wait(c.run(wf), {"completed", "failed"}, 60)
    assert r["status"] == "failed"
    deadline = time.time() + 20
    while time.time() < deadline and sum(1 for x in a.mock.calls if x.startswith("DELETE")) < 3:
        time.sleep(0.5)
    calls = [x for x in a.mock.calls]
    expected = ["POST /reserve", "POST /charge", "POST /ship", "DELETE /ship", "DELETE /charge", "DELETE /reserve"]
    assert calls == expected, calls
    return "forward " + " -> ".join(calls[:3]) + "; on failure compensated " + " -> ".join(calls[3:])


SCENARIOS = [("A sequential execution", s_sequential), ("B parallel execution", s_parallel),
             ("C worker crash (SIGKILL) + recovery", s_worker_crash), ("D/E/F approval across API + worker + Redis restart", s_approval_restart),
             ("G timer wait survives Redis data loss", s_timer_with_redis_loss), ("I lost queue message recovered", s_lost_queue_message),
             ("H callback continuation (+ duplicate)", s_callback), ("K rerun from node", s_rerun_from_node),
             ("J checkpoint restore", s_checkpoint_resume), ("L saga compensation ordering", s_saga)]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default="http://localhost:8000")
    for k in ("kill-worker", "start-worker", "stop-worker", "restart-api", "restart-redis", "flush-redis", "active-tasks"):
        p.add_argument(f"--{k}", default="")
    p.add_argument("--mock-host", default="127.0.0.1")
    p.add_argument("--mock-port", type=int, default=18099)
    p.add_argument("--recovery-timeout", type=int, default=180)
    p.add_argument("--only", default="", help="comma separated scenario letters, e.g. A,C,L")
    a = p.parse_args()
    a.mock = Mock("0.0.0.0", a.mock_port)
    mock_url = f"http://{a.mock_host}:{a.mock_port}"
    c = Client(a.base_url)
    failed = 0
    only = {x.strip().upper() for x in a.only.split(",") if x.strip()}
    for name, fn in SCENARIOS:
        if only and name.split()[0].split("/")[0] not in only:
            continue
        a.mock.calls.clear()
        t0 = time.time()
        try:
            detail = fn(c, a, mock_url) if fn is s_saga else fn(c, a)
            print(f"PASS  {name:<52} {time.time() - t0:6.1f}s  {detail}", flush=True)
        except Exception as e:  # noqa: BLE001 - report every scenario
            failed += 1
            print(f"FAIL  {name:<52} {time.time() - t0:6.1f}s  {type(e).__name__}: {e}", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
