from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Iterator

import httpx

TERMINAL = {"completed", "failed", "cancelled"}


class IsoclineError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(f"{code}: {message}")
        self.status, self.code, self.message, self.details = status, code, message, details


class _Http:
    def __init__(self, base_url: str, token: str | None, client: httpx.Client | None = None, timeout: float = 60):
        self.base = base_url.rstrip("/")
        self.token = token
        self.c = client or httpx.Client(base_url=self.base, timeout=timeout)

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"User-Agent": "isocline-sdk/2.0"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return {**h, **(extra or {})}

    def request(self, method: str, path: str, *, json_body: Any = None, params: dict | None = None, headers: dict | None = None) -> Any:
        r = self.c.request(method, path, json=json_body, params=params, headers=self._headers(headers))
        if r.status_code == 204:
            return None
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}
        if r.status_code >= 400:
            err = (data or {}).get("error", {}) if isinstance(data, dict) else {}
            raise IsoclineError(r.status_code, err.get("code", "error"), err.get("message", r.text[:300]), err.get("details"))
        return data

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, json_body=body if body is not None else {}, **kw)

    def put(self, path, body=None, **kw):
        return self.request("PUT", path, json_body=body, **kw)


class Run:
    """A workflow run. `wait()` polls until the run finishes or pauses for a human/external event."""

    def __init__(self, http: _Http, data: dict, public_key: str | None = None):
        self._h, self._key = http, public_key
        self.data = data
        self.id = data.get("id") or data.get("run_id")

    @property
    def status(self) -> str:
        return self.data.get("status")

    @property
    def output(self) -> Any:
        out = self.data.get("output")
        return out.get("result") if isinstance(out, dict) and "result" in out else out

    @property
    def error(self) -> Any:
        return self.data.get("error")

    def refresh(self) -> "Run":
        if self._key:
            self.data = self._h.get(f"/v1/runs/{self.id}", headers={"X-API-Key": self._key})
        else:
            self.data = self._h.get(f"/api/v1/runs/{self.id}")
        return self

    def wait(self, timeout: float = 600, poll: float = 1.0, until_waiting: bool = True) -> "Run":
        deadline = time.monotonic() + timeout
        while True:
            self.refresh()
            if self.status in TERMINAL or (until_waiting and self.status == "waiting"):
                return self
            if time.monotonic() > deadline:
                raise TimeoutError(f"Run {self.id} still {self.status} after {timeout}s")
            time.sleep(poll)

    def events(self) -> Iterator[dict]:
        """Streams run events (Server-Sent Events). Replays history first, then live events until the run ends."""
        with self._h.c.stream("GET", f"/api/v1/runs/{self.id}/events", headers=self._h._headers({"Accept": "text/event-stream"}),
                              timeout=None) as r:
            if r.status_code >= 400:
                raise IsoclineError(r.status_code, "stream_failed", r.read().decode()[:300])
            event = "message"
            for line in r.iter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    if event == "end":
                        return
                    yield payload
                    event = "message"

    def cancel(self) -> "Run":
        self.data = self._h.post(f"/api/v1/runs/{self.id}/cancel")
        return self

    def nodes(self) -> list[dict]:
        return self._h.get(f"/api/v1/runs/{self.id}/nodes")

    def trace(self) -> dict:
        """Harness records: plan, routing and policy decisions, checkpoints, waits, compensation, goal plans."""
        return self._h.get(f"/api/v1/runs/{self.id}/harness")

    def artifacts(self) -> list[dict]:
        return self._h.get(f"/api/v1/projects/{self.data.get('project_id')}/artifacts", params={"run_id": self.id})

    def __repr__(self) -> str:
        return f"<Run {self.id} {self.status}>"


class _Workflows:
    def __init__(self, h: _Http):
        self._h = h

    def list(self, project: str) -> list[dict]:
        return self._h.get(f"/api/v1/projects/{project}/workflows")

    def get(self, workflow_id: str) -> dict:
        return self._h.get(f"/api/v1/workflows/{workflow_id}")

    def resolve(self, workflow: str, project: str | None) -> str:
        try:
            uuid.UUID(workflow)
            return workflow
        except ValueError:
            if not project:
                raise ValueError("Pass project=<project id> to look a workflow up by name")
            return self._h.get(f"/api/v1/projects/{project}/workflow-lookup", params={"name": workflow})["id"]

    def create(self, project: str, name: str, graph: dict | Any, description: str = "") -> dict:
        g = graph.to_graph() if hasattr(graph, "to_graph") else graph
        return self._h.post(f"/api/v1/projects/{project}/workflows", {"name": name, "description": description, "graph": g})

    def update(self, workflow_id: str, graph: dict | Any) -> dict:
        g = graph.to_graph() if hasattr(graph, "to_graph") else graph
        cur = self.get(workflow_id)
        return self._h.put(f"/api/v1/workflows/{workflow_id}", {"graph": g, "revision": cur["revision"]})

    def plan(self, workflow_id: str) -> dict:
        return self._h.post(f"/api/v1/workflows/{workflow_id}/plan", {})

    def publish(self, workflow_id: str, notes: str = "") -> dict:
        return self._h.post(f"/api/v1/workflows/{workflow_id}/publish", {"notes": notes})

    def export(self, workflow_id: str) -> dict:
        return self._h.get(f"/api/v1/workflows/{workflow_id}/export")

    def run(self, workflow: str, input: Any = None, *, project: str | None = None, version: int | None = None,
            idempotency_key: str | None = None) -> Run:
        wid = self.resolve(workflow, project)
        r = self._h.post(f"/api/v1/workflows/{wid}/run", {"input": input or {}, "version": version, "idempotency_key": idempotency_key})
        return Run(self._h, {"id": r["run_id"], "status": r["status"]}).refresh()


class _Runs:
    def __init__(self, h):
        self._h = h

    def get(self, run_id: str) -> Run:
        return Run(self._h, {"id": run_id}).refresh()

    def list(self, workflow_id: str | None = None, project: str | None = None) -> list[dict]:
        if workflow_id:
            return self._h.get(f"/api/v1/workflows/{workflow_id}/runs")
        if project:
            return self._h.get(f"/api/v1/projects/{project}/runs")
        raise ValueError("pass workflow_id or project")

    def resume_from_checkpoint(self, run_id: str, checkpoint_id: str) -> Run:
        r = self._h.post(f"/api/v1/runs/{run_id}/resume", {"checkpoint_id": checkpoint_id})
        return self.get(r["run_id"])


class _Approvals:
    def __init__(self, h):
        self._h = h

    def list(self, workspace: str) -> list[dict]:
        return self._h.get(f"/api/v1/workspaces/{workspace}/approvals")

    def resolve(self, approval_id: str, decision: str, comment: str | None = None, edited_content: Any = None) -> dict:
        return self._h.post(f"/api/v1/approvals/{approval_id}/decide", {"decision": decision, "comment": comment, "edited_content": edited_content})


class _Projects:
    def __init__(self, h):
        self._h = h

    def list(self, workspace: str | None = None) -> list[dict]:
        """Projects of a workspace (default: every workspace the token's user belongs to)."""
        spaces = [workspace] if workspace else [w["id"] for w in self._h.get("/api/v1/auth/me")["workspaces"]]
        return [p for ws in spaces for p in self._h.get(f"/api/v1/workspaces/{ws}/projects")]


class _Artifacts:
    def __init__(self, h):
        self._h = h

    def get(self, artifact_id: str) -> dict:
        return self._h.get(f"/api/v1/artifacts/{artifact_id}")

    def list(self, project: str, **filters) -> list[dict]:
        return self._h.get(f"/api/v1/projects/{project}/artifacts", params={k: v for k, v in filters.items() if v})

    def download(self, artifact_id: str, path: str | None = None) -> bytes:
        r = self._h.c.get(f"/api/v1/artifacts/{artifact_id}/download", headers=self._h._headers())
        if r.status_code >= 400:
            raise IsoclineError(r.status_code, "download_failed", r.text[:300])
        if path:
            with open(path, "wb") as f:
                f.write(r.content)
        return r.content


class _Evaluations:
    def __init__(self, h):
        self._h = h

    def run(self, workflow_id: str, dataset_id: str, version: int | None = None, wait: bool = True, timeout: float = 1800) -> dict:
        er = self._h.post(f"/api/v1/workflows/{workflow_id}/evaluate", {"dataset_id": dataset_id, "version": version})
        deadline = time.monotonic() + timeout
        while wait:
            er = self._h.get(f"/api/v1/evaluations/{er['id']}")
            if er["status"] != "running":
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Evaluation still running")
            time.sleep(2)
        return er






class Isocline:
    def __init__(self, base_url: str | None = None, token: str | None = None, *, http_client: httpx.Client | None = None, timeout: float = 60):
        base_url = base_url or os.environ.get("ISOCLINE_URL", "http://localhost:3000")
        token = token or os.environ.get("ISOCLINE_TOKEN")
        self._h = _Http(base_url, token, http_client, timeout)
        self.workflows = _Workflows(self._h)
        self.runs = _Runs(self._h)
        self.projects = _Projects(self._h)
        self.approvals = _Approvals(self._h)
        self.artifacts = _Artifacts(self._h)
        self.evaluations = _Evaluations(self._h)

    def me(self) -> dict:
        return self._h.get("/api/v1/auth/me")

    def validate(self, project: str, document: dict) -> dict:
        return self._h.post(f"/api/v1/projects/{project}/validate-document", {"document": document})
