# Python SDK

`pip install -e sdk/python` (package `isocline-sdk`, module `isocline_sdk`, Python ≥ 3.10, depends on httpx).

```python
from isocline_sdk import Isocline, Workflow

client = Isocline(base_url="http://localhost:8000", token="isc_pat_...")   # or ISOCLINE_URL / ISOCLINE_TOKEN
project = client.projects.list()[0]["id"]

wf = Workflow("Company research")                       # builder API
wf.input("company")
wf.agent("research", prompt="Research {{input.company}}", model="local_test/echo")
created = client.workflows.create(project, "Company research", wf)

run = client.workflows.run(created["id"], {"company": "Acme Corp"})   # id or name (+ project)
run.wait()                        # returns at completed/failed/cancelled, or when waiting (until_waiting=True)
print(run.status, run.output, run.error)
for ev in client.runs.get(run.id).events():   # Server-Sent Events: history, then live
    print(ev["type"])
print(run.nodes(), run.trace())               # per-node records; harness records (checkpoints, waits, ...)
```

Surface: `projects.list`; `workflows.list/get/create/update/plan/publish/export/run/resolve`; `runs.get/list/
resume_from_checkpoint`; `Run.status/output/error/refresh/wait/events/cancel/nodes/trace/artifacts`;
`approvals.list/resolve`; `artifacts.list/get/download`; `evaluations.run`;
`validate(project, document)`; `me()`. Errors raise `IsoclineError(status, code, message, details)`.
Tokens: Settings → Access tokens (`POST /api/v1/tokens`).
