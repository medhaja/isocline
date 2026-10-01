#!/usr/bin/env python3
"""Create every workflow template on a running Isocline, run it with its sample input and check it completes.

Only dependency: httpx  (pip install httpx)

    # 1. In the UI: Settings -> Access tokens -> create one (isc_pat_...)
    # 2. Free and deterministic: checks the workflow mechanics with the built-in test provider (no API key)
    python scripts/template_check.py --token isc_pat_...
    # 3. With a real model (costs money: ~2-6 model calls per template)
    python scripts/template_check.py --token isc_pat_... --model openai/gpt-5-mini --timeout 300
    # only some templates
    python scripts/template_check.py --token isc_pat_... --category "Job seekers"
    python scripts/template_check.py --token isc_pat_... --only job_resume_tailor,creator_youtube_package

ISOCLINE_URL and ISOCLINE_TOKEN environment variables work too. Without a token the script registers a throwaway
account, which only works when sign-up is open (ISOCLINE_ALLOW_SIGNUP=true).

Workflows are created in a separate project ("Template check <time>") so your projects stay clean; delete it in the
UI afterwards, or pass --cleanup to delete it when the check passes. Human-approval steps are approved automatically.
A JSON report (status, model calls, tokens, cost, error per template) is written to --report.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime

try:
    import httpx
except ImportError:
    sys.exit("This script needs httpx:  pip install httpx")

API = "/api/v1"
if hasattr(sys.stdout, "reconfigure"):  # Windows consoles: never crash on characters the code page lacks
    sys.stdout.reconfigure(errors="replace")


def client(base: str, token: str | None) -> httpx.Client:
    h = httpx.Client(base_url=base.rstrip("/"), timeout=60)
    if token:
        h.headers["Authorization"] = f"Bearer {token}"
        r = h.get(f"{API}/auth/me")
        if r.status_code == 401:
            sys.exit("The token was rejected (401). Create a new one under Settings -> Access tokens.")
        r.raise_for_status()
        return h
    r = h.post(f"{API}/auth/register", json={"email": f"tpl-{uuid.uuid4().hex[:8]}@example.com", "password": "template-check-pw"})
    if r.status_code == 403:
        sys.exit("Sign-up is closed on this installation. Pass --token isc_pat_... (Settings -> Access tokens).")
    r.raise_for_status()
    tok = h.post(f"{API}/tokens", json={"name": "template-check"}, headers={"X-CSRF-Token": h.cookies.get("isc_csrf")}).json()["token"]
    h.cookies.clear()
    h.headers["Authorization"] = f"Bearer {tok}"
    return h


def run_template(h: httpx.Client, pid: str, t: dict, provider: str, model: str, timeout: int) -> dict:
    t0 = time.time()
    res = {"id": t["id"], "name": t["name"], "category": t.get("category"), "status": "error"}
    wf = h.post(f"{API}/projects/{pid}/workflows", json={"name": t["name"], "template_id": t["id"],
                                                          "model": {"provider": provider, "model": model}})
    if wf.status_code >= 400:
        return {**res, "error": f"create failed ({wf.status_code}): {wf.text[:300]}"}
    wid = wf.json()["id"]
    v = h.post(f"{API}/workflows/{wid}/validate", json={}).json()
    errs = [i["message"] for i in v.get("issues", []) if i["severity"] == "error"]
    res["warnings"] = [i["message"] for i in v.get("issues", []) if i["severity"] == "warning"]
    if errs:
        return {**res, "status": "invalid", "error": "; ".join(errs)[:500], "workflow_id": wid}
    rr = h.post(f"{API}/workflows/{wid}/run", json={"input": t["sample_input"]})
    if rr.status_code != 202:
        return {**res, "error": f"run rejected ({rr.status_code}): {rr.text[:300]}", "workflow_id": wid}
    rid = rr.json()["run_id"]
    approvals = 0
    run: dict = {}
    while time.time() - t0 < timeout:
        run = h.get(f"{API}/runs/{rid}").json()
        if run["status"] == "waiting":
            for ap in h.get(f"{API}/runs/{rid}/approvals").json():
                if ap["status"] == "pending":
                    h.post(f"{API}/approvals/{ap['id']}/decide", json={"decision": "approved", "comment": "template_check.py"})
                    approvals += 1
        if run["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(1)
    else:
        return {**res, "status": "timeout", "error": f"still {run.get('status')} after {timeout}s", "run_id": rid, "workflow_id": wid}
    err = run.get("error") or {}
    out = run.get("output")
    return {**res, "status": run["status"], "run_id": rid, "workflow_id": wid, "approvals": approvals,
            "llm_calls": run.get("llm_calls"), "tokens": (run.get("input_tokens") or 0) + (run.get("output_tokens") or 0),
            "cost_usd": run.get("cost_usd"), "seconds": round(time.time() - t0, 1),
            "error": err.get("message") if isinstance(err, dict) else (str(err) if err else None),
            "output_preview": (json.dumps(out) if not isinstance(out, str) else out)[:400] if out is not None else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("ISOCLINE_URL", "http://localhost:8000"))
    ap.add_argument("--token", default=os.environ.get("ISOCLINE_TOKEN"))
    ap.add_argument("--model", default="local_test/json", help="provider/model, e.g. openai/gpt-5-mini (default: free test provider)")
    ap.add_argument("--only", default="", help="comma-separated template ids")
    ap.add_argument("--category", default="", help='e.g. "Job seekers" (see docs/templates.md)')
    ap.add_argument("--timeout", type=int, default=120, help="seconds per template (use 300+ for real models)")
    ap.add_argument("--report", default="template_check_report.json")
    ap.add_argument("--cleanup", action="store_true", help="delete the test project if every template passed")
    a = ap.parse_args()
    if "/" not in a.model:
        sys.exit("--model must be provider/model, e.g. openai/gpt-5-mini")
    provider, model = a.model.split("/", 1)

    h = client(a.base_url, a.token)
    ws = h.get(f"{API}/auth/me").json()["workspaces"][0]["id"]
    templates = h.get(f"{API}/templates").json()
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    templates = [t for t in templates if (not only or t["id"] in only) and (not a.category or (t.get("category") or "").lower() == a.category.lower())]
    if not templates:
        sys.exit("No templates match --only / --category.")
    project = h.post(f"{API}/workspaces/{ws}/projects", json={"name": f"Template check {datetime.now():%Y-%m-%d %H:%M}",
                                                              "description": "Created by scripts/template_check.py"}).json()
    print(f"{len(templates)} template(s) | model {a.model} | project '{project['name']}' | {a.base_url}\n")

    results = []
    for i, t in enumerate(templates, 1):
        try:
            r = run_template(h, project["id"], t, provider, model, a.timeout)
        except Exception as e:  # noqa: BLE001 - keep going and report
            r = {"id": t["id"], "name": t["name"], "category": t.get("category"), "status": "error", "error": f"{type(e).__name__}: {e}"}
        results.append(r)
        ok = r["status"] == "completed"
        extra = f"{r.get('llm_calls', 0):>2} calls {r.get('tokens', 0):>6} tok ${r.get('cost_usd') or 0:.4f} {r.get('seconds', 0):>5}s" \
            + ("  approved" if r.get("approvals") else "") if ok else (r.get("error") or "")[:160]
        print(f"[{i:>2}/{len(templates)}] {'PASS' if ok else r['status'].upper():<9} {r['id']:<34} {extra}", flush=True)

    passed = [r for r in results if r["status"] == "completed"]
    cost = sum(r.get("cost_usd") or 0 for r in results)
    with open(a.report, "w", encoding="utf-8") as f:
        json.dump({"base_url": a.base_url, "model": a.model, "project_id": project["id"], "passed": len(passed),
                   "total": len(results), "estimated_cost_usd": round(cost, 4), "results": results}, f, indent=2)
    print(f"\n{len(passed)}/{len(results)} passed | estimated cost ${cost:.4f} | report: {a.report}")
    if len(passed) != len(results):
        print("Failed runs can be opened in the UI: /runs/<run_id> (ids are in the report).")
    elif a.cleanup:
        h.delete(f"{API}/projects/{project['id']}")
        print("Test project deleted.")
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
