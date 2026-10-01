#!/usr/bin/env python3
"""Run an example against a self-hosted Isocline.

    export ISOCLINE_URL=http://localhost:8000
    export ISOCLINE_TOKEN=isc_pat_...        # Settings -> Access tokens
    python examples/run_example.py examples/01-simple-agent
    python examples/run_example.py examples/04-human-approval --approve
    python examples/run_example.py examples/production-agent-demo --approve

Imports the example's workflow.json into your first project (or --project), performs the example's setup (knowledge
base upload, MCP server registration, event publishing, local mock API), runs it with input.json and prints the
result, per-node status, tokens and cost. Requires only the Python SDK (pip install -e sdk/python).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk" / "python"))
from isocline_sdk import Isocline  # noqa: E402

API = "/api/v1"


def mock_api(port: int) -> list[str]:
    """Stand-in for an external order system (10-saga-compensation). Records every call."""
    calls: list[str] = []

    class H(BaseHTTPRequestHandler):
        def _do(self):
            self.rfile.read(int(self.headers.get("content-length") or 0))
            calls.append(f"{self.command} {self.path}")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        do_POST = do_DELETE = do_GET = _do

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return calls


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("example")
    p.add_argument("--workflow-file", default="workflow.json")
    p.add_argument("--project")
    p.add_argument("--approve", action="store_true", help="approve pending human approvals automatically")
    p.add_argument("--mcp-url", default=os.environ.get("MCP_URL", "http://host.docker.internal:8766/mcp"))
    p.add_argument("--mock-port", type=int, default=18099)
    p.add_argument("--mock-base", default=os.environ.get("MOCK_BASE", "http://host.docker.internal:18099"))
    p.add_argument("--timeout", type=int, default=300)
    a = p.parse_args()
    ex = Path(a.example)
    c = Isocline(base_url=os.environ.get("ISOCLINE_URL", "http://localhost:8000"), token=os.environ.get("ISOCLINE_TOKEN"))
    me = c.me()
    ws = me["workspaces"][0]["id"]
    project = a.project or c.projects.list(ws)[0]["id"]
    doc = json.loads((ex / a.workflow_file).read_text())
    inp = json.loads((ex / "input.json").read_text())
    calls = None

    if ex.name == "05-rag":  # knowledge base with the sample handbook
        kbs = [k for k in c._h.get(f"{API}/projects/{project}/knowledge-bases") if k["name"] == "Acme handbook"]
        kb = kbs[0] if kbs else c._h.post(f"{API}/projects/{project}/knowledge-bases", {"name": "Acme handbook"})
        if not kbs:
            f = ex / "acme-handbook.md"
            r = c._h.c.post(f"{API}/knowledge-bases/{kb['id']}/documents", headers=c._h._headers(),
                            files={"file": (f.name, f.read_bytes(), "text/markdown")})
            r.raise_for_status()
            for _ in range(120):
                d = c._h.get(f"{API}/knowledge-bases/{kb['id']}/documents")[0]
                if d["status"] in ("ready", "failed"):
                    break
                time.sleep(1)
            print(f"knowledge base 'Acme handbook': document {d['status']}", file=sys.stderr)
        doc = json.loads(json.dumps(doc).replace("__KB_ACME_HANDBOOK__", kb["id"]))
    if ex.name == "07-mcp":  # register the example MCP server as "crm"
        servers = {s["name"]: s for s in c._h.get(f"{API}/workspaces/{ws}/mcp")}
        srv = servers.get("crm") or c._h.post(f"{API}/workspaces/{ws}/mcp", {"name": "crm", "endpoint": a.mcp_url, "allowed_tools": ["lookup_account"]})
        c._h.post(f"{API}/mcp/{srv['id']}/sync", {})
        print(f"MCP server 'crm' at {srv['endpoint']} synced", file=sys.stderr)
    if ex.name == "10-saga-compensation":
        calls = mock_api(a.mock_port)
        inp["api_base"] = a.mock_base

    wf = c._h.post(f"{API}/projects/{project}/workflows/import", {"document": doc})
    v = c._h.post(f"{API}/workflows/{wf['id']}/validate", {})
    for i in v["issues"]:
        print(f"  {i['severity']}: {i['message']}", file=sys.stderr)
    if not v["valid"]:
        print("Workflow is not valid on this installation (see above).", file=sys.stderr)
        return 1
    run = c.workflows.run(wf["id"], inp)
    print(f"run {run.id} started  (UI: /runs/{run.id})", file=sys.stderr)
    end = time.time() + a.timeout
    published = False
    while time.time() < end:
        run.refresh()
        if run.status in ("completed", "failed", "cancelled"):
            break
        if run.status == "waiting":
            pending = [x for x in c._h.get(f"{API}/runs/{run.id}/approvals") if x["status"] == "pending"]
            if pending and a.approve:
                for x in pending:
                    c.approvals.resolve(x["id"], "approved", comment="approved by run_example.py")
                    print(f"approved: {x['title']}", file=sys.stderr)
            elif pending:
                print("waiting for approval: decide in the UI (Approvals) or re-run with --approve", file=sys.stderr)
                return 2
            if ex.name == "08-durable-wait" and not published:
                waits = c._h.get(f"{API}/runs/{run.id}/harness").get("waits", [])
                if any(w.get("kind") == "event" and w.get("status") == "waiting" for w in waits):
                    c._h.post(f"{API}/workspaces/{ws}/events", {"name": "payment.settled", "correlation_key": inp["order"]["order_id"],
                                                                 "payload": {"amount": 1200, "currency": "USD"}})
                    print("published event payment.settled for ORD-1042", file=sys.stderr)
                    published = True
        time.sleep(1)
    print(json.dumps({"status": run.status, "output": run.output, "error": run.error, "llm_calls": run.data.get("llm_calls"),
                      "tokens": (run.data.get("input_tokens") or 0) + (run.data.get("output_tokens") or 0),
                      "cost_usd": run.data.get("cost_usd"),
                      "nodes": {n["node_key"]: n["status"] for n in run.nodes() if not n.get("scope")}}, indent=2, default=str))
    if calls is not None:
        time.sleep(3)
        print("external calls: " + " -> ".join(calls), file=sys.stderr)
    if ex.name == "10-saga-compensation":  # success = the forward steps ran, the last step failed, undo ran in reverse
        expected = ["POST /reserve", "POST /charge", "POST /ship", "DELETE /ship", "DELETE /charge", "DELETE /reserve"]
        ok = run.status == "failed" and calls == expected
        print("saga compensation " + ("verified" if ok else f"NOT as expected: {calls}"), file=sys.stderr)
        return 0 if ok else 1
    return 0 if run.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
