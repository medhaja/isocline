"""Isocline Python SDK.

    from isocline_sdk import Isocline
    client = Isocline(base_url="https://isocline.example.com", token="isc_pat_...")
    run = client.workflows.run("financial-analysis", project="<project id>", input={"company": "Acme Corp"})
    result = run.wait()
    print(result.output)

(The import name is `isocline_sdk` so it never collides with the server package `isocline`.)"""
from .client import Isocline, IsoclineError, Run
from .workflow import Workflow

__all__ = ["Isocline", "IsoclineError", "Run", "Workflow"]
__version__ = "2.0.0"
