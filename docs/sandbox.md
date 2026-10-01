# Python sandbox

Python nodes and the `python` tool run in a separate service (`python-sandbox`) that starts **one disposable container
per execution** (`workers/python-sandbox/app.py`):

| Control | Setting |
|---|---|
| Disposable | `docker run --rm`; a fresh container every time; orphans from a crashed controller are removed on its startup |
| Network | `--network none` (no network at all; there is no option to enable it in this service) |
| Filesystem | `--read-only` root; writable tmpfs only: `/work` (64 MB, owned by the sandbox user) and `/tmp` (64 MB); no host mounts |
| User / privileges | uid 65534 (`nobody`), `--cap-drop ALL`, `--security-opt no-new-privileges`, never `--privileged` |
| CPU / memory | `--cpus` `SANDBOX_CPUS` (0.5), `--memory` = `--memory-swap` = `SANDBOX_MEMORY` (256m) |
| Processes | `--pids-limit` `SANDBOX_PIDS` (64) — fork bombs hit the limit |
| File size | `--ulimit fsize` 16 MB |
| Wall clock | the controller kills the container at the node timeout (max `SANDBOX_MAX_TIMEOUT`, 60 s); an in-container `timeout --signal=KILL` (timeout + 10 s) is a second, independent clock |
| Output | stdout/stderr captured (64 KB each); files written to `out/` returned as artifacts (≤ 20 files, ≤ 1 MB each) |
| Concurrency | `SANDBOX_MAX_CONCURRENCY` (4) executions at a time per controller |
| Auth | bearer token shared with the API; the controller is not published on a host port |
| Runtime | `SANDBOX_RUNTIME=runsc` runs containers under gVisor if installed on the host |

The runner image contains Python 3.12 with numpy, pandas, scipy and matplotlib.

## Limitations — read before running untrusted code

- **Plain Docker is not a hardened isolation boundary.** Containers share the host kernel; a kernel vulnerability can
  lead to escape. For untrusted or adversarial code use gVisor (`SANDBOX_RUNTIME=runsc`) or run the sandbox service on a
  dedicated VM.
- **The controller holds the Docker socket**, which is equivalent to root on that host. Compromise of the controller
  (it only accepts authenticated requests from the API) means compromise of the host. Prefer a rootless or remote Docker
  daemon (`DOCKER_HOST`) on a separate machine for shared installations.
- Resource limits bound one execution; `SANDBOX_MAX_CONCURRENCY` bounds how many run at once. A workflow can still
  queue many executions; the runtime's tool-call ceilings bound that.
- **Process mode** (`SANDBOX_MODE=process`) runs code as a subprocess with rlimits and **is not isolation**. It is
  refused unless `SANDBOX_ALLOW_UNSAFE_PROCESS=true` and exists for development and CI only.

## What was verified

The exact `docker run` arguments are asserted by `workers/python-sandbox/tests` (removing any isolation flag fails CI);
the protocol, timeout, error reporting, file artifacts and orphan reaping are tested; Python nodes were run end to end
through the live stack in process mode. The Docker-mode limits were **not** exercised in the release verification
environment (no Docker available). CI builds the images; please report results from real hosts.

Design: [design/python-sandbox.md](design/python-sandbox.md).
