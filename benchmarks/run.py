#!/usr/bin/env python3
"""Isocline benchmarks. Measures the real implementation; nothing is estimated or synthesized.

    # in-process (needs apps/api installed):     python benchmarks/run.py compile
    # against a live stack (API + worker + beat): python benchmarks/run.py live --base-url http://localhost:8000
    # both, results to benchmarks/results/<timestamp>.json:  python benchmarks/run.py all --base-url ...

Live benchmarks poll the API frequently: start the API under test with ISOCLINE_RATE_LIMIT_PER_MINUTE=100000.
Live benchmarks use the deterministic local test provider (ISOCLINE_ENABLE_TEST_PROVIDER=true, no model latency) and
need sign-up open or a fresh install. Every figure is reported with its sample count; results depend on hardware,
worker concurrency and configuration, which are printed with the results.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
API = "/api/v1"


def pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def summary(name, ms, unit="ms", note=""):
    return {"name": name, "samples": len(ms), "unit": unit, "p50": round(pct(ms, 50), 3), "p95": round(pct(ms, 95), 3),
            "p99": round(pct(ms, 99), 3), "mean": round(statistics.mean(ms), 3), "note": note}


def node(id_, type_, key=None, **config):
    return {"id": id_, "key": key or id_, "type": type_, "name": id_, "position": {"x": 0, "y": 0}, "config": config}


def edge(s, t):
    return {"id": f"e_{s}_{t}", "source": s, "target": t}


def chain(n):
    nodes = [node("in", "input_text", "inp", field="topic")]
    edges = []
    prev = "in"
    for i in range(n - 2):
        nid = f"t{i}"
        nodes.append(node(nid, "transform", f"step_{i}", mode="template", template="{{inp.output}} " + str(i)))
        edges.append(edge(prev, nid))
        prev = nid
    nodes.append(node("out", "output_text", "result"))
    edges.append(edge(prev, "out"))
    return {"schema_version": "1.0", "nodes": nodes, "edges": edges, "settings": {"max_parallel_nodes": 32}}


def fanout(n):
    nodes = [node("in", "input_text", "inp", field="topic"), node("p", "parallel", "fan")]
    edges = [edge("in", "p")]
    for i in range(n):
        nodes.append(node(f"b{i}", "agent", f"branch_{i}", model={"provider": "local_test", "model": "echo"}, prompt="{{inp.output}}"))
        edges += [edge("p", f"b{i}"), edge(f"b{i}", "m")]
    nodes += [node("m", "merge", "merged", strategy="named"), node("out", "output_json", "result")]
    edges.append(edge("m", "out"))
    return {"schema_version": "1.0", "nodes": nodes, "edges": edges, "settings": {"max_parallel_nodes": 32, "max_llm_calls": 100}}


def bench_compile(samples=50):
    from isocline.engine.graph import compile_graph, validate_structure
    from isocline.schemas.workflow import WorkflowGraph
    out = []
    for n in (10, 100, 500):
        raw = chain(n)
        ms = []
        for _ in range(samples if n < 500 else max(10, samples // 5)):
            t0 = time.perf_counter()
            g = WorkflowGraph.model_validate(raw)
            validate_structure(g)
            compile_graph(g)
            ms.append((time.perf_counter() - t0) * 1000)
        out.append(summary(f"compile+validate {n}-node graph", ms, note="parse, structural validation, compile; in-process"))
    return out


class Live:
    def __init__(self, base):
        import httpx
        self.httpx = httpx
        self.h = httpx.Client(base_url=base, timeout=60)
        r = self.h.post(f"{API}/auth/register", json={"email": f"bench-{uuid.uuid4().hex[:8]}@example.com", "password": "benchmark-password"})
        r.raise_for_status()
        self.ws = r.json()["workspace_id"]
        tok = self.h.post(f"{API}/tokens", json={"name": "bench"}, headers={"X-CSRF-Token": self.h.cookies.get("isc_csrf")}).json()["token"]
        self.h.cookies.clear()
        self.h.headers["Authorization"] = f"Bearer {tok}"
        self.pid = self.h.get(f"{API}/workspaces/{self.ws}/projects").json()[0]["id"]

    def post(self, url, body):
        r = self.h.post(url, json=body)
        r.raise_for_status()
        return r.json()

    def wf(self, g):
        return self.post(f"{API}/projects/{self.pid}/workflows", {"name": f"bench-{uuid.uuid4().hex[:6]}", "graph": g})["id"]

    def run_and_wait(self, wf, statuses=("completed", "failed")):
        rid = self.post(f"{API}/workflows/{wf}/run", {"input": {"topic": "Acme"}})["run_id"]
        while True:
            resp = self.h.get(f"{API}/runs/{rid}")
            if resp.status_code == 429:
                raise SystemExit("Rate limited by the API: run the benchmark against an API started with "
                                 "ISOCLINE_RATE_LIMIT_PER_MINUTE=100000 (see benchmarks/README.md).")
            r = resp.json()
            if r["status"] in statuses:
                return r
            time.sleep(0.02)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def bench_live(base, samples):
    L = Live(base)
    out = []
    # 1. queue pickup: run created -> worker started (Redis queue + Celery prefork + atomic claim in PostgreSQL)
    wf = L.wf(chain(3))
    pick, e2e = [], []
    for _ in range(samples):
        t0 = time.perf_counter()
        r = L.run_and_wait(wf)
        e2e.append((time.perf_counter() - t0) * 1000)
        pick.append((ts(r["started_at"]) - ts(r["created_at"])) * 1000)
    out.append(summary("queue pickup (run created -> execution started)", pick, note="API -> Redis -> Celery worker -> claim"))
    out.append(summary("3-node run end-to-end, client observed", e2e, note="includes 20 ms client polling granularity"))
    # 2. per-node scheduling overhead on a 50-node chain of deterministic transforms (persisted node runs + events)
    wf = L.wf(chain(50))
    per = []
    for _ in range(max(3, samples // 5)):
        r = L.run_and_wait(wf)
        per.append((ts(r["finished_at"]) - ts(r["started_at"])) * 1000 / 50)
    out.append(summary("per-node overhead, 50-node sequential chain", per, note="execution time / nodes; each node persists state + events"))
    # 3. parallel fan-out of 32 agent branches (local test provider, no model latency)
    wf = L.wf(fanout(32))
    fo = []
    for _ in range(max(3, samples // 5)):
        r = L.run_and_wait(wf)
        fo.append((ts(r["finished_at"]) - ts(r["started_at"])) * 1000)
    out.append(summary("32-branch parallel fan-out + merge, execution time", fo, note="max_parallel_nodes=32"))
    # 4. durable continuation: approval decided -> run completed (DB update -> enqueue -> new worker claim -> resume)
    g = {"schema_version": "1.0", "settings": {}, "nodes": [node("in", "input_text", "inp", field="topic"), node("ok", "human_approval", "review"),
         node("out", "output_text", "result")], "edges": [edge("in", "ok"), {"id": "e2", "source": "ok", "target": "out", "source_handle": "approved"}]}
    wf = L.wf(g)
    cont = []
    for _ in range(max(5, samples // 2)):
        r = L.run_and_wait(wf, ("waiting",))
        ap = L.h.get(f"{API}/runs/{r['id']}/approvals").json()[0]
        t0 = time.perf_counter()
        L.post(f"{API}/approvals/{ap['id']}/decide", {"decision": "approved"})
        while L.h.get(f"{API}/runs/{r['id']}").json()["status"] != "completed":
            time.sleep(0.01)
        cont.append((time.perf_counter() - t0) * 1000)
    out.append(summary("durable continuation (approve -> run completed)", cont, note="resume from PostgreSQL on a new task"))
    # 5. HTTP tool overhead against a local no-op server (SSRF check + DNS pinning + request + persistence)
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 18077), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    g = {"schema_version": "1.0", "settings": {}, "nodes": [node("in", "input_text", "inp", field="topic"),
         node("h", "tool_http", "call", arguments={"url": "http://127.0.0.1:18077/"}), node("out", "output_json", "result")],
         "edges": [edge("in", "h"), edge("h", "out")]}
    wf = L.wf(g)
    ht = []
    for _ in range(samples):
        r = L.run_and_wait(wf)
        if r["status"] != "completed":
            out.append({"name": "HTTP tool node", "note": "NOT MEASURED: needs ISOCLINE_ALLOW_PRIVATE_NETWORK_HOSTS to include 127.0.0.1"})
            break
        n = [x for x in L.h.get(f"{API}/runs/{r['id']}/nodes").json() if x["node_key"] == "call"][0]
        ht.append((ts(n["finished_at"]) - ts(n["started_at"])) * 1000)
    if ht:
        out.append(summary("HTTP tool node (local no-op server)", ht, note="node started -> finished"))
    # 6. knowledge retrieval latency (search API, 200 chunks, configured embedding provider)
    kb = L.post(f"{API}/projects/{L.pid}/knowledge-bases", {"name": "bench", "chunk_size": 200, "chunk_overlap": 0})
    text = "\n\n".join(f"Section {i}. Acme product {i} ships in {i % 7 + 1} days and costs {i * 3} dollars. " * 2 for i in range(200))
    r = L.h.post(f"{API}/knowledge-bases/{kb['id']}/documents", files={"file": ("bench.txt", text.encode(), "text/plain")})
    r.raise_for_status()
    for _ in range(120):
        d = L.h.get(f"{API}/knowledge-bases/{kb['id']}/documents").json()[0]
        if d["status"] in ("ready", "failed"):
            break
        time.sleep(0.5)
    kq = []
    for i in range(samples * 2):
        t0 = time.perf_counter()
        L.post(f"{API}/knowledge-bases/{kb['id']}/search", {"query": f"how long does product {i} take to ship", "top_k": 5})
        kq.append((time.perf_counter() - t0) * 1000)
    out.append(summary(f"knowledge search API ({d.get('chunk_count', '?')} chunks)", kq, note="HTTP round trip incl. auth; embedding provider as configured"))
    return out


def environment(base=None):
    info = {"timestamp": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(), "os": platform.platform(),
            "machine": platform.machine(), "cpus": os.cpu_count()}
    try:
        info["cpu_model"] = next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
        info["mem_gb"] = round(int(next(l.split()[1] for l in open("/proc/meminfo") if l.startswith("MemTotal"))) / 1024 / 1024, 1)
    except Exception:
        pass
    for k in ("ISOCLINE_DATABASE_URL", "ISOCLINE_EMBEDDING_PROVIDER", "WORKER_CONCURRENCY", "BENCH_DB_VERSION", "BENCH_REDIS_VERSION", "BENCH_NOTES"):
        if os.environ.get(k):
            v = os.environ[k]
            info[k.lower()] = v.split("@")[-1] if "DATABASE_URL" in k else v
    if base:
        info["base_url"] = base
    return info


def main():
    p = argparse.ArgumentParser()
    p.add_argument("what", choices=["compile", "live", "all"])
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--samples", type=int, default=30)
    a = p.parse_args()
    res = []
    if a.what in ("compile", "all"):
        res += bench_compile(a.samples)
    if a.what in ("live", "all"):
        res += bench_live(a.base_url, a.samples)
    doc = {"environment": environment(a.base_url if a.what != "compile" else None), "results": res}
    print(json.dumps(doc["environment"], indent=2))
    print(f"\n{'benchmark':<55} {'n':>4} {'p50':>9} {'p95':>9} {'p99':>9}")
    for r in res:
        if "p50" in r:
            print(f"{r['name']:<55} {r['samples']:>4} {r['p50']:>9.2f} {r['p95']:>9.2f} {r['p99']:>9.2f}  {r['unit']}")
        else:
            print(f"{r['name']:<55} {r['note']}")
    out = ROOT / "benchmarks" / "results" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(doc, indent=2))
    print(f"\nwritten {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
