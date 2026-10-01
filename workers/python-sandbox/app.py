"""Isocline Python sandbox service.

Each /execute call runs user code in a NEW, disposable container:
  --network none, read-only root fs, tmpfs working dir, non-root user, all capabilities dropped,
  no-new-privileges, memory/CPU/PID limits and a hard wall-clock timeout (container is killed).
Optionally uses gVisor (SANDBOX_RUNTIME=runsc) for kernel-level isolation.

This service needs access to a Docker daemon. Run it on a dedicated host or VM (or use a rootless
/remote Docker daemon); do not share the daemon with the rest of the platform in production.

SANDBOX_MODE=process runs code in a local subprocess with rlimits. It is NOT an isolation boundary
and is refused unless SANDBOX_ALLOW_UNSAFE_PROCESS=true (for local development and tests only)."""
from __future__ import annotations

import asyncio
import hmac
import shutil
import json
import os
import resource
import sys
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

TOKEN = os.environ.get("SANDBOX_TOKEN", "")
MODE = os.environ.get("SANDBOX_MODE", "docker")
IMAGE = os.environ.get("SANDBOX_IMAGE", "isocline-sandbox-runner:latest")
RUNTIME = os.environ.get("SANDBOX_RUNTIME", "")  # e.g. "runsc" for gVisor
MEMORY = os.environ.get("SANDBOX_MEMORY", "256m")
CPUS = os.environ.get("SANDBOX_CPUS", "0.5")
PIDS = os.environ.get("SANDBOX_PIDS", "64")
MAX_TIMEOUT = int(os.environ.get("SANDBOX_MAX_TIMEOUT", "60"))
MAX_CONCURRENCY = int(os.environ.get("SANDBOX_MAX_CONCURRENCY", "4"))
HARNESS = (Path(__file__).parent / "harness.py").read_text()
MARK = "__AF_SANDBOX__"

app = FastAPI(title="Isocline Python Sandbox")
_slots = asyncio.Semaphore(MAX_CONCURRENCY)


class ExecuteIn(BaseModel):
    code: str = Field(max_length=200_000)
    inputs: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=600)


def _auth(authorization: str | None):
    if not TOKEN:
        raise HTTPException(503, "Sandbox token not configured")
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {TOKEN}"):
        raise HTTPException(401, "Unauthorized")


def _parse(stdout: bytes, stderr: bytes, returncode: int | None, timed_out: bool, timeout: int) -> dict:
    if timed_out:
        return {"success": False, "stdout": "", "stderr": "", "error": f"Execution exceeded the {timeout}s time limit and was killed",
                "files": [], "timed_out": True}
    text = stdout.decode("utf-8", "replace")
    if MARK in text:
        return {**json.loads(text.rsplit(MARK, 1)[1].strip()), "timed_out": False}
    err = stderr.decode("utf-8", "replace")[-4000:]
    if returncode in (-24, 152):
        return {"success": False, "stdout": "", "stderr": "", "error": f"CPU time limit of {timeout}s exceeded", "files": [], "timed_out": True}
    if returncode in (137, -9):
        err = "Process was killed (memory limit exceeded?)\n" + err
    return {"success": False, "stdout": text[-4000:], "stderr": err, "error": f"Sandbox exited with code {returncode}",
            "files": [], "timed_out": False}


async def _run(cmd: list[str], payload: bytes, timeout: int, cwd: str | None = None, preexec=None, on_timeout=None):
    proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, cwd=cwd, preexec_fn=preexec)
    try:
        out, err = await asyncio.wait_for(proc.communicate(payload), timeout=timeout)
        return out, err, proc.returncode, False
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        if on_timeout:
            await on_timeout()
        await proc.wait()
        return b"", b"", None, True


DOCKER_MISSING = ("The sandbox is in docker mode but the `docker` CLI is not installed in the python-sandbox image. "
                  "Rebuild it: docker compose build python-sandbox")


def docker_cli() -> str | None:
    return shutil.which("docker")


async def docker_status() -> dict:
    """Can this service actually start sandbox containers? (CLI present, daemon reachable, runner image present)"""
    if not docker_cli():
        return {"ok": False, "error": DOCKER_MISSING}
    try:
        p = await asyncio.create_subprocess_exec("docker", "version", "--format", "{{.Server.Version}}",
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(p.communicate(), 8)
    except (OSError, asyncio.TimeoutError) as e:
        return {"ok": False, "error": f"Docker daemon not reachable: {e}"}
    if p.returncode != 0:
        return {"ok": False, "error": "Docker daemon not reachable (is /var/run/docker.sock mounted, or DOCKER_HOST set?): "
                                      + err.decode("utf-8", "replace").strip()[:300]}
    p = await asyncio.create_subprocess_exec("docker", "image", "inspect", IMAGE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await p.wait()
    if p.returncode != 0:
        return {"ok": False, "error": f"Runner image {IMAGE} not found. Build it: docker compose build sandbox-runner"}
    return {"ok": True, "daemon": out.decode().strip()}


LABEL = "isocline.sandbox=1"


def docker_command(name: str, timeout: int) -> list[str]:
    """The exact isolation boundary for one execution (asserted by tests/test_sandbox.py)."""
    cmd = ["docker", "run", "--rm", "-i", "--name", name, "--label", LABEL, "--network", "none", "--read-only",
           "--tmpfs", "/tmp:rw,size=64m,mode=1777", "--tmpfs", "/work:rw,size=64m,uid=65534,gid=65534,mode=0700",
           "--workdir", "/work", "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--memory", MEMORY, "--memory-swap", MEMORY, "--cpus", CPUS, "--pids-limit", PIDS, "--ulimit", "fsize=16777216",
           "--env", "PYTHONDONTWRITEBYTECODE=1"]
    if RUNTIME:
        cmd += ["--runtime", RUNTIME]
    # Second, independent wall clock inside the container: if this controller dies mid-execution the container is
    # still killed (the controller's own timeout + `docker kill` is the first).
    cmd += [IMAGE, "timeout", "--signal=KILL", str(timeout + 10), "python", "-I", "-c", HARNESS]
    return cmd


async def reap_orphans() -> int:
    """Removes sandbox containers left behind by a previous controller process (crash, restart)."""
    try:
        p = await asyncio.create_subprocess_exec("docker", "ps", "-aq", "--filter", f"label={LABEL}",
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(p.communicate(), 10)
        ids = out.decode().split()
        if ids:
            r = await asyncio.create_subprocess_exec("docker", "rm", "-f", *ids, stdout=asyncio.subprocess.DEVNULL,
                                                     stderr=asyncio.subprocess.DEVNULL)
            await r.wait()
        return len(ids)
    except (OSError, asyncio.TimeoutError):
        return 0


async def run_docker(req: ExecuteIn, timeout: int) -> dict:
    if not docker_cli():
        raise HTTPException(503, DOCKER_MISSING)
    name = f"isc-sbx-{uuid.uuid4().hex[:12]}"
    cmd = docker_command(name, timeout)

    async def kill():
        p = await asyncio.create_subprocess_exec("docker", "kill", name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await p.wait()
    try:
        out, err, rc, to = await _run(cmd, json.dumps(req.model_dump()).encode(), timeout + 5, on_timeout=kill)
    except OSError as e:
        raise HTTPException(503, f"Could not start a sandbox container: {e}")
    if rc == 125 or (rc and b"Cannot connect to the Docker daemon" in err):
        raise HTTPException(503, "Could not start a sandbox container: " + err.decode("utf-8", "replace").strip()[-400:])
    return _parse(out, err, rc, to, timeout)


async def run_process(req: ExecuteIn, timeout: int) -> dict:
    if os.environ.get("SANDBOX_ALLOW_UNSAFE_PROCESS") != "true":
        raise HTTPException(503, "Process mode is disabled: it is not an isolation boundary")

    def limits():
        mem = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 << 20, 16 << 20))
        os.setsid()
    with tempfile.TemporaryDirectory(prefix="isc-sbx-") as d:
        env_cmd = [sys.executable, "-I", "-c", HARNESS]
        out, err, rc, to = await _run(env_cmd, json.dumps(req.model_dump()).encode(), timeout, cwd=d, preexec=limits)
        return _parse(out, err, rc, to, timeout)


@app.post("/execute")
async def execute(req: ExecuteIn, authorization: str | None = Header(default=None)):
    _auth(authorization)
    timeout = min(req.timeout_seconds, MAX_TIMEOUT)
    async with _slots:
        return await (run_docker(req, timeout) if MODE == "docker" else run_process(req, timeout))


@app.on_event("startup")
async def check_runtime():
    if MODE == "docker":
        st = await docker_status()
        if not st["ok"]:
            print(f"[python-sandbox] NOT READY: {st['error']}", file=sys.stderr, flush=True)
        else:
            n = await reap_orphans()
            if n:
                print(f"[python-sandbox] removed {n} orphaned sandbox container(s)", file=sys.stderr, flush=True)


@app.get("/healthz")
async def health():
    """Reports whether code can actually run (503 when not), so orchestrators and `docker compose ps` show it."""
    if MODE == "docker":
        st = await docker_status()
        if not st["ok"]:
            raise HTTPException(503, st["error"])
        return {"ok": True, "mode": MODE, "docker": st.get("daemon")}
    return {"ok": True, "mode": MODE}
