# Isocline Python SDK & CLI

```bash
pip install ./sdk/python        # installs the `isocline_sdk` package and the `isocline` command
isocline login --url http://localhost:3000 --token isc_pat_...   # create tokens under Settings → Access tokens
```

```python
from isocline_sdk import Isocline, Workflow

client = Isocline(base_url="http://localhost:3000", token="isc_pat_...")
run = client.workflows.run("Company Research", project="<project id>", input={"company": "Acme Corp"})
result = run.wait()
print(result.status, result.output)

for event in client.runs.get(run.id).events():      # stream (replays history, then live)
    print(event["type"])

wf = Workflow("analysis")
company = wf.input("company")
research = wf.agent("research", prompt="Research {{input.company}}", model="auto", tools=["web_search"])
report = wf.output("report", format="markdown")
company >> research >> report
client.workflows.create("<project id>", "Analysis", wf)     # same schema as the visual editor
```

Covers workflows, runs (wait, stream, cancel, traces), approvals, artifacts and evaluations. Import name is `isocline_sdk` so it never collides with the server
package `isocline`.
