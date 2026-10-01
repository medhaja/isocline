# Design: Python sandbox

## Problem
Agents and workflows need real computation (pandas, statistics, file generation). Running generated code in the API or
worker would expose credentials, the database network and the host.

## Design
A separate service (`python-sandbox`) receives `{code, inputs, timeout}` over an authenticated internal HTTP call and
runs a harness inside a **fresh container per execution**: no network, read-only root with small tmpfs mounts, nobody
user, all capabilities dropped, no-new-privileges, memory/CPU/PID/file-size limits, and two independent kill clocks
(controller `docker kill`; in-container `timeout --signal=KILL`). The harness executes the code with `INPUTS`, captures
stdout/stderr, and returns files from `out/` (bounded count and size) as base64; the worker turns them into artifacts.
The result is framed after a marker on the real stdout, so user prints cannot corrupt the protocol. Leftover labelled
containers are removed when the controller starts. Optional gVisor via `--runtime runsc`.

## Threat model
In scope: code that tries to read secrets (none are present), reach the network (no interface), exhaust resources
(limits), persist (disposable), or escalate within the container (no capabilities, no setuid gain). Out of scope for
plain Docker: kernel exploits — mitigated only by gVisor or a VM. The controller's Docker socket is a privileged
capability: isolate the controller host for shared installations.

## Tradeoffs
Container start latency (hundreds of ms, not measured in the reference environment) per execution in exchange for no
state leaking between executions. No network means no `pip install` at run time: the runner image carries common data
libraries. Process mode exists only for development and CI and refuses to start without an explicit unsafe flag.

## Alternatives
Pyodide/WASM (strong isolation, weak library support), long-lived pooled containers (faster, but state leaks between
tenants), firecracker microVMs (strongest; heavier to operate — a future backend behind the same HTTP protocol).
