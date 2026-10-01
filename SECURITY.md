# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 3.3.x (first public open-source release) | yes |
| < 3.3 (pre-release internal versions) | no |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately through GitHub: **Security → Report a vulnerability** on this repository (GitHub private vulnerability
reporting). Include the affected version or commit, a description, reproduction steps and the impact you expect.

What to expect:

- acknowledgement within 3 business days;
- an initial assessment (confirmed / needs more information / not a vulnerability) within 10 business days;
- a fix or mitigation plan for confirmed issues, coordinated with you; we ask for up to 90 days before public disclosure;
- credit in the release notes if you want it.

The project is maintained by volunteers; there is no bug bounty and no SLA beyond the above.

## Scope

In scope: the API, workers, web UI, Python sandbox controller and runner image, SDK/CLI, Docker Compose defaults.
Especially interesting: sandbox escapes, SSRF bypasses in the HTTP tool / MCP client, authentication or tenant-isolation
bypasses, secret disclosure (credentials in traces, exports or logs), and durable-state corruption.

Out of scope: vulnerabilities that require an already-compromised host or Docker daemon, denial of service by an
and authenticated administrator actions within their own installation.

The security model and its limits are documented in [docs/security.md](docs/security.md) and [docs/sandbox.md](docs/sandbox.md).
