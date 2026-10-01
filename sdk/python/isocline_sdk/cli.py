"""isocline CLI — for developers and CI pipelines.

  isocline login --url https://isocline.example.com --token isc_pat_...
  isocline validate workflow.json --project <id>              exit 1 if BLOCKED
  isocline run <workflow> --project <id> --input '{"company":"Acme"}' [--stream]   exit 1 if the run fails
  isocline evaluate <workflow> --dataset <id>                  exit 1 if pass rate < --min-pass-rate
Configuration: ~/.isocline/config.json, or ISOCLINE_URL / ISOCLINE_TOKEN."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .client import Isocline, IsoclineError

CONFIG = Path(os.environ.get("ISOCLINE_CONFIG", Path.home() / ".isocline" / "config.json"))


def _client(args) -> Isocline:
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    return Isocline(base_url=os.environ.get("ISOCLINE_URL") or cfg.get("url"), token=os.environ.get("ISOCLINE_TOKEN") or cfg.get("token"))


def _print(obj, as_json: bool):
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
    elif isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, indent=2, default=str))


def cmd_login(args):
    c = Isocline(base_url=args.url, token=args.token)
    me = c.me()
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({"url": args.url, "token": args.token}))
    os.chmod(CONFIG, 0o600)
    print(f"Logged in as {me['user']['email']}")
    return 0


def cmd_validate(args):
    c = _client(args)
    doc = json.loads(Path(args.file).read_text())
    project = args.project or c.projects.list()[0]["id"]
    res = c.validate(project, doc)
    if args.json:
        _print(res, True)
    else:
        print(f"Status: {res['status']}")
        for i in res["issues"]:
            print(f"  {i['severity']:7} {i.get('code', '')}: {i['message']}")
        if res.get("plan"):
            t = res["plan"]["totals"]
            print(f"  estimated calls {t['llm_calls'][0]}–{t['llm_calls'][1]}, cost ${t['cost_usd'][0]:.2f}–${t['cost_usd'][1]:.2f}, "
                  f"active time {t['active_seconds'][0]}–{t['active_seconds'][1]}s")
            for ch in res["plan"]["checks"]:
                if ch["status"] == "fail":
                    print(f"  BLOCKED {ch['category']}: {ch['message']}")
    return 0 if res["valid"] else 1


def cmd_run(args):
    c = _client(args)
    run = c.workflows.run(args.workflow, json.loads(args.input or "{}"), project=args.project, version=args.version)
    print(f"Run {run.id} started", file=sys.stderr)
    if args.stream:
        for ev in run.events():
            d = ev.get("data") or {}
            print(f"{ev['seq']:>4} {ev['type']:<22} {d.get('node_id', '')}", file=sys.stderr)
    run.wait(timeout=args.timeout)
    if run.status == "waiting":
        print("Run is waiting for approval or an external event", file=sys.stderr)
        _print({"run_id": run.id, "status": run.status}, args.json)
        return 2
    _print(run.output if run.status == "completed" else run.error, args.json)
    return 0 if run.status == "completed" else 1


def cmd_projects_list(args):
    rows = _client(args).projects.list(args.workspace)
    if args.json:
        _print(rows, True)
    else:
        for p in rows:
            print(f"{p['id']}  {p['name']}")
    return 0


def cmd_workflows_list(args):
    c = _client(args)
    projects = [args.project] if args.project else [p["id"] for p in c.projects.list()]
    rows = [w for pid in projects for w in c.workflows.list(pid)]
    if args.json:
        _print(rows, True)
    else:
        for w in rows:
            print(f"{w['id']}  {w.get('status', ''):<10} {w['name']}")
    return 0


def cmd_runs_get(args):
    c = _client(args)
    run = c.runs.get(args.run_id)
    d = dict(run.data)
    if args.nodes:
        d["nodes"] = [{k: n.get(k) for k in ("node_key", "status", "input_tokens", "output_tokens", "cost_usd", "error")} for n in run.nodes()]
    if not args.json:
        d.pop("graph_snapshot", None)
    _print(d, args.json)
    return 0 if d.get("status") not in ("failed",) else 1


def cmd_artifacts_get(args):
    c = _client(args)
    meta = c.artifacts.get(args.artifact_id)
    if args.output:
        c.artifacts.download(args.artifact_id, args.output)
        print(f"Saved {meta.get('name', args.artifact_id)} to {args.output}", file=sys.stderr)
    _print(meta, args.json)
    return 0


def cmd_evaluate(args):
    c = _client(args)
    wid = c.workflows.resolve(args.workflow, args.project)
    er = c.evaluations.run(wid, args.dataset, args.version)
    s = er.get("summary") or {}
    _print({"status": er["status"], "pass_rate": s.get("pass_rate"), "passed": s.get("passed"), "cases": s.get("cases"),
            "avg_latency_ms": s.get("avg_latency_ms"), "total_cost_usd": s.get("total_cost_usd")}, args.json)
    return 0 if (s.get("pass_rate") or 0) >= args.min_pass_rate else 1








def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="isocline", description="Isocline CLI: validate, run and inspect workflows on a self-hosted Isocline")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("login"); s.add_argument("--url", required=True); s.add_argument("--token", required=True); s.set_defaults(fn=cmd_login)
    s = sub.add_parser("validate"); s.add_argument("file"); s.add_argument("--project", help="project to validate against (default: your first project)"); s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("run"); s.add_argument("workflow"); s.add_argument("--project"); s.add_argument("--input"); s.add_argument("--version", type=int)
    s.add_argument("--stream", action="store_true"); s.add_argument("--timeout", type=float, default=600); s.set_defaults(fn=cmd_run)
    s = sub.add_parser("projects", help="projects"); ps = s.add_subparsers(dest="sub", required=True)
    s = ps.add_parser("list"); s.add_argument("--workspace"); s.set_defaults(fn=cmd_projects_list)
    s = sub.add_parser("workflows", help="workflows"); ws = s.add_subparsers(dest="sub", required=True)
    s = ws.add_parser("list"); s.add_argument("--project"); s.set_defaults(fn=cmd_workflows_list)
    s = sub.add_parser("runs", help="runs"); rs = s.add_subparsers(dest="sub", required=True)
    s = rs.add_parser("get"); s.add_argument("run_id"); s.add_argument("--nodes", action="store_true", help="include per-node status, tokens, cost")
    s.set_defaults(fn=cmd_runs_get)
    s = sub.add_parser("artifacts", help="artifacts"); as_ = s.add_subparsers(dest="sub", required=True)
    s = as_.add_parser("get"); s.add_argument("artifact_id"); s.add_argument("-o", "--output", help="download the content to this path")
    s.set_defaults(fn=cmd_artifacts_get)
    s = sub.add_parser("evaluate"); s.add_argument("workflow"); s.add_argument("--project"); s.add_argument("--dataset", required=True)
    s.add_argument("--version", type=int); s.add_argument("--min-pass-rate", type=float, default=0.0); s.set_defaults(fn=cmd_evaluate)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except IsoclineError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        if e.details:
            for d in (e.details if isinstance(e.details, list) else [e.details])[:10]:
                print(f"  - {d.get('message') if isinstance(d, dict) else d}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
