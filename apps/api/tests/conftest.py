"""Test harness: SQLite (aiosqlite) database per test, in-process dispatcher, local_test provider."""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("ISOCLINE_ENV", "test")
os.environ.setdefault("ISOCLINE_ENABLE_TEST_PROVIDER", "true")
os.environ.setdefault("ISOCLINE_STORAGE_LOCAL_PATH", "/tmp/isocline-test-uploads")
os.environ.setdefault("ISOCLINE_ALLOW_SIGNUP", "true")  # multi-account tests (tenant isolation); tests/oss covers the default

import pytest_asyncio

from isocline.db import session as dbs
from isocline.db.models import Base, Project, User, Workflow, Workspace
from isocline.engine.events import MemoryBus
from isocline.engine.executor import Executor
from isocline.engine.store import SqlRunStore
from isocline.services import dispatch


@pytest_asyncio.fixture
async def db(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    dbs.configure(url)
    async with dbs.engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    queued: list[str] = []
    dispatch.set_dispatcher(queued.append)
    async with dbs.sessionmaker()() as s:
        s.info["queued"] = queued
        yield s
    dispatch.set_dispatcher(None)
    await dbs.engine().dispose()


@pytest_asyncio.fixture
async def env(db):
    user = User(email=f"u{uuid.uuid4().hex[:6]}@example.com", password_hash="x", name="Tester")
    db.add(user)
    await db.flush()
    ws = Workspace(name="WS", owner_id=user.id)
    db.add(ws)
    await db.flush()
    proj = Project(workspace_id=ws.id, name="P")
    db.add(proj)
    await db.commit()
    return {"user": user, "workspace": ws, "project": proj, "db": db}


def node(id_, type_, key=None, **config):
    return {"id": id_, "key": key or id_, "type": type_, "name": id_.title(), "position": {"x": 0, "y": 0}, "config": config}


def agent(id_, model="echo", **extra):
    cfg = {"model": {"provider": "local_test", "model": model}, "prompt": "Work on: {{input.topic}}"}
    cfg.update(extra)
    return node(id_, "agent", **cfg)


def edge(s, t, sh=None, th=None):
    return {"id": f"e_{s}_{t}_{sh or ''}", "source": s, "target": t, "source_handle": sh, "target_handle": th}


def graph(nodes, edges, **settings):
    return {"schema_version": "1.0", "nodes": nodes, "edges": edges, "settings": settings}


async def make_workflow(env, g, name="WF") -> Workflow:
    db = env["db"]
    wf = Workflow(project_id=env["project"].id, name=name, graph=g, created_by=env["user"].id)
    db.add(wf)
    await db.commit()
    return wf


async def run_graph(env, g, run_input=None, bus=None, skip_plan=False):
    """Creates a run through the real service layer and executes it in-process."""
    from isocline.services.runs import create_run
    wf = await make_workflow(env, g)
    run = await create_run(env["db"], workflow=wf, project=env["project"], run_input=run_input or {"topic": "acme"},
                           user_id=env["user"].id, dispatch=False, skip_plan=skip_plan)
    bus = bus or MemoryBus()
    status = await Executor(SqlRunStore(bus), str(run.id)).execute()
    return run, status, bus, wf


async def reload_run(env, run_id):
    from isocline.db.models import Run
    async with dbs.sessionmaker()() as s:
        return await s.get(Run, run_id)


async def node_runs(run_id):
    from sqlalchemy import select
    from isocline.db.models import NodeRun
    async with dbs.sessionmaker()() as s:
        rows = (await s.execute(select(NodeRun).where(NodeRun.run_id == run_id))).scalars().all()
        return {(r.node_key if not r.scope else f"{r.node_key}@{r.scope}"): r for r in rows}


# ------------------------------------------------------------------ HTTP-level harness
class Api:
    """Thin client that behaves like the browser: session cookie + double-submit CSRF header."""

    def __init__(self, client):
        self.c = client

    def _h(self):
        tok = self.c.cookies.get("isc_csrf")
        return {"X-CSRF-Token": tok} if tok else {}

    async def get(self, url, **kw):
        return await self.c.get(url, **kw)

    async def post(self, url, json=None, **kw):
        return await self.c.post(url, json=json, headers={**self._h(), **kw.pop("headers", {})}, **kw)

    async def put(self, url, json=None, **kw):
        return await self.c.put(url, json=json, headers=self._h(), **kw)

    async def patch(self, url, json=None, **kw):
        return await self.c.patch(url, json=json, headers=self._h(), **kw)

    async def delete(self, url, **kw):
        return await self.c.delete(url, headers=self._h(), **kw)


@pytest_asyncio.fixture
async def app_env(tmp_path):
    import httpx
    from isocline.db.seed import seed
    from isocline.main import create_app
    from isocline.services import ratelimit
    from isocline.services.evaluation import set_eval_dispatcher
    ratelimit.reset_local()
    url = f"sqlite+aiosqlite:///{tmp_path}/api.db"
    dbs.configure(url)
    async with dbs.engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with dbs.sessionmaker()() as s:
        await seed(s)
    queued_runs: list[str] = []
    queued_evals: list[str] = []
    dispatch.set_dispatcher(queued_runs.append)
    dispatch.set_ingest_dispatcher(lambda _id: None)
    set_eval_dispatcher(queued_evals.append)
    app = create_app()
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))

    def new_client():
        return Api(httpx.AsyncClient(transport=transport, base_url="http://test"))
    yield {"new": new_client, "runs": queued_runs, "evals": queued_evals}
    dispatch.set_dispatcher(None)
    dispatch.set_ingest_dispatcher(None)
    set_eval_dispatcher(None)
    await dbs.engine().dispose()


async def drain(queued: list[str]) -> None:
    """Executes queued runs in-process, like a worker would."""
    while queued:
        rid = queued.pop(0)
        await Executor(SqlRunStore(MemoryBus()), rid).execute()


async def drain_everything(app_env) -> None:
    """Runs queued runs and evaluations until nothing is left."""
    from isocline.services.evaluation import execute_evaluation
    for _ in range(20):
        progressed = False
        if app_env["runs"]:
            await drain(app_env["runs"])
            progressed = True
        while app_env["evals"]:
            await execute_evaluation(app_env["evals"].pop(0), executor_factory=True)
            progressed = True
        if not progressed:
            return


async def signup(api, email="alice@example.com"):
    r = await api.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery", "name": email.split("@")[0]})
    assert r.status_code == 201, r.text
    return r.json()
