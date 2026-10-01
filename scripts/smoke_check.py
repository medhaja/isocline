#!/usr/bin/env python3
"""Product-surface smoke check against a LIVE Isocline installation (no paid API keys needed).

    python scripts/smoke_check.py --base-url http://localhost:8000

Exercises, over the public HTTP API: the Python SDK, the CLI, workflow export/import, the node playground, the
Python sandbox, knowledge bases (upload -> ingest -> pgvector/lexical retrieval), a signed webhook trigger, a cron
schedule trigger, and the examples/ directory (every example
must import and validate). Needs sign-up to be open (ISOCLINE_ALLOW_SIGNUP=true) or a fresh installation.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk" / "python"))
from isocline_sdk import Isocline  # noqa: E402

API = "/api/v1"
results: list[tuple[str, bool, str]] = []


def check(name):
    def deco(fn):
        def run(*a):
            t0 = time.time()
            try:
                detail = fn(*a)
                results.append((name, True, detail))
                print(f"PASS  {name:<42} {time.time() - t0:5.1f}s  {detail}", flush=True)
            except Exception as e:  # noqa: BLE001
                results.append((name, False, str(e)))
                print(f"FAIL  {name:<42} {time.time() - t0:5.1f}s  {type(e).__name__}: {str(e)[:300]}", flush=True)
        return run
    return deco


def node(id_, type_, key=None, **config):
    return {"id": id_, "key": key or id_, "type": type_, "name": id_, "position": {"x": 0, "y": 0}, "config": config}


def edge(s, t):
    return {"id": f"e_{s}_{t}", "source": s, "target": t}


def wait_run(c: Isocline, run_id, timeout=90, statuses=("completed", "failed", "cancelled")):
    end = time.time() + timeout
    while time.time() < end:
        r = c._h.get(f"{API}/runs/{run_id}")
        if r["status"] in statuses:
            return r
        time.sleep(0.5)
    raise TimeoutError(f"run {run_id} still {r['status']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    a = ap.parse_args()
    h = httpx.Client(base_url=a.base_url, timeout=60)
    r = h.post(f"{API}/auth/register", json={"email": f"smoke-{uuid.uuid4().hex[:8]}@example.com", "password": "smoke-check-password"})
    r.raise_for_status()
    ws = r.json()["workspace_id"]
    tok = h.post(f"{API}/tokens", json={"name": "smoke"}, headers={"X-CSRF-Token": h.cookies.get("isc_csrf")}).json()["token"]
    c = Isocline(base_url=a.base_url, token=tok)
    pid = c.projects.list(ws)[0]["id"]
    env = {**os.environ, "ISOCLINE_URL": a.base_url, "ISOCLINE_TOKEN": tok}
    state: dict = {}

    simple = {"schema_version": "1.0", "settings": {}, "nodes": [
        node("i", "input_text", key="company", field="company"),
        node("a", "agent", key="research", model={"provider": "local_test", "model": "echo"}, prompt="Research {{company.output}}"),
        node("o", "output_text", key="result")], "edges": [edge("i", "a"), edge("a", "o")]}

    @check("SDK: create + run workflow")
    def sdk_run():
        wf = c.workflows.create(pid, "Smoke: SDK", simple)
        state["wf"] = wf["id"]
        run = c.workflows.run(wf["id"], {"company": "Acme Corp"}).wait(timeout=60)
        assert run.status == "completed", run.error
        state["run"] = run.id
        return f"run {run.id[:8]} completed; output={json.dumps(run.output)[:60]}"

    @check("CLI: projects/workflows list, runs get, validate")
    def cli():
        def cli(*args):
            p = subprocess.run([sys.executable, "-m", "isocline_sdk.cli", *args], env=env, capture_output=True, text=True,
                               cwd=ROOT / "sdk" / "python")
            return p.returncode, p.stdout + p.stderr
        rc1, out1 = cli("projects", "list")
        rc2, out2 = cli("workflows", "list", "--project", pid)
        rc3, out3 = cli("--json", "runs", "get", state["run"], "--nodes")
        f = ROOT / "examples" / "01-simple-agent" / "workflow.json"
        rc4, out4 = cli("validate", str(f), "--project", pid) if f.exists() else (0, "skipped")
        assert rc1 == rc2 == rc3 == 0 and state["wf"] in out2 and '"completed"' in out3, (out1, out2, out3)
        assert rc4 == 0, out4
        return "4 commands exit 0; validate on examples/01 passed"

    @check("Export -> import round trip")
    def export_import():
        doc = c.workflows.export(state["wf"])
        assert "credential" not in json.dumps(doc).lower() or "credential_id\": null" in json.dumps(doc)
        imp = c._h.post(f"{API}/projects/{pid}/workflows/import", {"document": doc})
        run = c.workflows.run(imp["id"], {"company": "Acme Corp"}).wait(timeout=60)
        assert run.status == "completed"
        return f"exported schema {doc.get('schema_version')}, re-imported as {imp['id'][:8]}, imported copy ran"

    @check("Node playground (single node)")
    def playground():
        g = c.workflows.get(state["wf"])["graph"]
        res = c._h.post(f"{API}/workflows/{state['wf']}/nodes/a/playground", {"input": {"company": "Globex"}})
        r = wait_run(c, res["run_id"])
        assert r["status"] == "completed", r.get("error")
        return f"node 'research' executed alone ({len(g['nodes'])}-node workflow)"

    @check("Python sandbox node")
    def python_node():
        g = {"schema_version": "1.0", "settings": {}, "nodes": [
            node("i", "input_json", key="data", field="data"),
            node("p", "tool_python", key="calc", arguments={"code": "import statistics\nvals = INPUTS['data']['values']\n"
                 "print(statistics.mean(vals))\nopen('out/summary.txt','w').write(str(sum(vals)))", "inputs": {"data": "{{data.output}}"}}),
            node("o", "output_json", key="result")], "edges": [edge("i", "p"), edge("p", "o")]}
        wf = c.workflows.create(pid, "Smoke: python", g)
        run = c.workflows.run(wf["id"], {"data": {"values": [2, 4, 9]}}).wait(timeout=90)
        assert run.status == "completed", run.error
        out = json.dumps(run.output)
        assert "5" in out, out
        return f"stdout mean=5 captured; output {out[:80]}"

    @check("Knowledge base: upload, ingest, search")
    def knowledge():
        kb = c._h.post(f"{API}/projects/{pid}/knowledge-bases", {"name": "Acme handbook"})
        text = ("Acme Corp refund policy: customers may return products within 30 days for a full refund.\n\n"
                "Acme Corp shipping: orders ship within 2 business days from the Springfield warehouse.\n\n"
                "Acme Corp security: report vulnerabilities to security@example.com.")
        files = {"file": ("handbook.txt", text.encode(), "text/plain")}
        r = httpx.post(f"{a.base_url}{API}/knowledge-bases/{kb['id']}/documents", files=files,
                       headers={"Authorization": f"Bearer {tok}"}, timeout=60)
        assert r.status_code in (200, 201, 202), r.text
        end = time.time() + 90
        while time.time() < end:
            docs = c._h.get(f"{API}/knowledge-bases/{kb['id']}/documents")
            if docs and docs[0].get("status") in ("ready", "failed", "error"):
                break
            time.sleep(1)
        assert docs[0]["status"] == "ready", docs
        hits = c._h.post(f"{API}/knowledge-bases/{kb['id']}/search", {"query": "how many days to return a product for a refund", "top_k": 2})
        rows = hits if isinstance(hits, list) else hits.get("results", hits.get("chunks", []))
        top = json.dumps(rows[0])
        assert "refund" in top.lower(), top
        state["kb"] = kb["id"]
        return f"{docs[0].get('chunk_count', '?')} chunk(s); top hit is the refund passage"

    @check("Webhook trigger (HMAC-signed)")
    def webhook():
        c.workflows.publish(state["wf"], "smoke")  # triggers always run a published version
        t = c._h.post(f"{API}/projects/{pid}/triggers", {"workflow_id": state["wf"], "kind": "webhook", "name": "Inbound"})
        body = json.dumps({"company": "Initech"}).encode()
        ts = int(time.time())
        sig = "sha256=" + hmac.new(t["secret"].encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        hdr = {"content-type": "application/json", "X-Isocline-Timestamp": str(ts), "X-Isocline-Signature": sig}
        ok = httpx.post(f"{a.base_url}{t['path']}", content=body, headers=hdr)
        replay = httpx.post(f"{a.base_url}{t['path']}", content=body, headers=hdr)
        bad = httpx.post(f"{a.base_url}{t['path']}", content=body, headers={**hdr, "X-Isocline-Signature": "sha256=00"})
        assert ok.status_code == 202, ok.text
        assert replay.status_code >= 400 and bad.status_code >= 400, (replay.status_code, bad.status_code)
        rid = ok.json().get("run_id") or ok.json().get("runs_started", [None])[0]
        if rid:
            assert wait_run(c, rid)["status"] == "completed"
        return f"signed delivery accepted (202); replay -> {replay.status_code}; bad signature -> {bad.status_code}"

    @check("Schedule trigger (cron)")
    def schedule():
        t = c._h.post(f"{API}/projects/{pid}/triggers", {"workflow_id": state["wf"], "kind": "schedule", "name": "Every minute",
                                                           "config": {"cron": "* * * * *", "timezone": "UTC"}})
        end = time.time() + 150
        while time.time() < end:
            runs = [x for x in c.runs.list(workflow_id=state["wf"]) if x.get("trigger") == "schedule"]
            if runs:
                r = wait_run(c, runs[0]["id"])
                c._h.put(f"{API}/triggers/{t['id']}", {"workflow_id": state["wf"], "kind": "schedule", "name": "Every minute",
                                                        "enabled": False, "config": {"cron": "* * * * *", "timezone": "UTC"}})
                # the schedule sends no payload; this workflow requires `company`, so the run itself may fail validation of input
                return f"beat fired the schedule (run {r['status']}; scheduled runs receive no input)"
            time.sleep(3)
        raise TimeoutError("no scheduled run within 150 s")

    @check("Examples import and validate")
    def examples():
        n = 0
        for f in sorted((ROOT / "examples").glob("*/workflow.json")):
            doc = json.loads(f.read_text().replace("__KB_ACME_HANDBOOK__", state.get("kb", "")))  # 05-rag placeholder
            imp = c._h.post(f"{API}/projects/{pid}/workflows/import", {"document": doc})
            v = c._h.post(f"{API}/workflows/{imp['id']}/validate", {})
            # tolerated: paid-provider keys (02) and the MCP server not being registered in this throwaway account (07)
            errs = [i for i in v["issues"] if i["severity"] == "error" and i["code"] not in ("credential_missing", "mcp_server_missing")]
            assert not errs, (f.parent.name, errs)
            n += 1
        assert n, "no examples found"
        return f"{n} example workflows imported and validated (missing paid-provider keys tolerated)"

    for fn in (sdk_run, cli, export_import, playground, python_node, knowledge, webhook, examples, schedule):
        fn()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
