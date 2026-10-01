"""Harness/protocol tests using process mode (docker isolation itself is verified in deployment)."""
import os

os.environ["SANDBOX_TOKEN"] = "t"
os.environ["SANDBOX_MODE"] = "process"
os.environ["SANDBOX_ALLOW_UNSAFE_PROCESS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

import app as sbx  # noqa: E402

c = TestClient(sbx.app)
H = {"Authorization": "Bearer t"}


def test_requires_token():
    assert c.post("/execute", json={"code": "print(1)"}).status_code == 401


def test_executes_with_inputs_and_files():
    code = "import json\nprint(sum(INPUTS['xs']))\nopen('out/r.json','w').write(json.dumps({'ok':1}))"
    r = c.post("/execute", headers=H, json={"code": code, "inputs": {"xs": [1, 2, 3]}}).json()
    assert r["success"] and r["stdout"].strip() == "6" and r["files"][0]["name"] == "r.json"


def test_errors_are_reported():
    r = c.post("/execute", headers=H, json={"code": "1/0"}).json()
    assert not r["success"] and "ZeroDivisionError" in r["error"]


def test_timeout_kills():
    r = c.post("/execute", headers=H, json={"code": "while True: pass", "timeout_seconds": 1}).json()
    assert not r["success"]


def test_process_mode_refused_without_opt_in():
    os.environ["SANDBOX_ALLOW_UNSAFE_PROCESS"] = "false"
    try:
        assert c.post("/execute", headers=H, json={"code": "print(1)"}).status_code == 503
    finally:
        os.environ["SANDBOX_ALLOW_UNSAFE_PROCESS"] = "true"


def test_docker_mode_without_docker_cli_is_a_clear_503(monkeypatch):
    """Regression: in docker mode with no `docker` binary in the image, /execute crashed with a 500
    (FileNotFoundError from create_subprocess_exec). It must answer 503 with an actionable message,
    and /healthz must report the service as not ready."""
    monkeypatch.setattr(sbx, "MODE", "docker")
    monkeypatch.setenv("PATH", "/nonexistent")
    r = c.post("/execute", headers=H, json={"code": "print(1)"})
    assert r.status_code == 503 and "docker` CLI is not installed" in r.json()["detail"]
    h = c.get("/healthz")
    assert h.status_code == 503 and "Rebuild it" in h.json()["detail"]


def test_docker_mode_with_unreachable_daemon_is_a_clear_503(monkeypatch, tmp_path):
    """A docker CLI that cannot reach a daemon (socket not mounted) is reported, not crashed on."""
    fake = tmp_path / "docker"
    fake.write_text("#!/bin/sh\necho 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setattr(sbx, "MODE", "docker")
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    h = c.get("/healthz")
    assert h.status_code == 503 and "daemon not reachable" in h.json()["detail"]
    r = c.post("/execute", headers=H, json={"code": "print(1)"})
    assert r.status_code == 503 and "Cannot connect to the Docker daemon" in r.json()["detail"]


def test_docker_command_is_the_documented_isolation_boundary():
    """docs/sandbox.md describes these flags; removing one must fail CI."""
    import app as sbx
    cmd = sbx.docker_command("isc-sbx-test", 30)
    joined = " ".join(cmd)
    for flag in ("--rm", "--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--user 65534:65534", f"--memory {sbx.MEMORY}", f"--memory-swap {sbx.MEMORY}", f"--cpus {sbx.CPUS}",
                 f"--pids-limit {sbx.PIDS}", "--ulimit fsize=16777216", "--label isocline.sandbox=1"):
        assert flag in joined, flag
    assert "-v" not in cmd and "--volume" not in cmd and "--privileged" not in cmd, "no host mounts, never privileged"
    i = cmd.index(sbx.IMAGE)
    assert cmd[i + 1:i + 4] == ["timeout", "--signal=KILL", "40"], "in-container wall clock"


def test_gvisor_runtime_is_passed_through(monkeypatch):
    import app as sbx
    monkeypatch.setattr(sbx, "RUNTIME", "runsc")
    cmd = sbx.docker_command("x", 5)
    assert cmd[cmd.index("--runtime") + 1] == "runsc"


def test_orphans_are_reaped(monkeypatch, tmp_path):
    """A fake docker CLI records calls: labelled leftovers from a crashed controller are removed on startup."""
    import asyncio
    import os
    import app as sbx
    log = tmp_path / "calls"
    fake = tmp_path / "docker"
    fake.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n[ \"$1\" = ps ] && printf 'abc123\\ndef456\\n'\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    assert asyncio.run(sbx.reap_orphans()) == 2
    calls = log.read_text().splitlines()
    assert calls[0] == "ps -aq --filter label=isocline.sandbox=1"
    assert calls[1] == "rm -f abc123 def456"
