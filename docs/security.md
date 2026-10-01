# Security model

## Trust boundaries

| Boundary | Trusted side | Untrusted side | Control |
|---|---|---|---|
| Browser → API | API | browser | session cookie (HttpOnly, SameSite=Lax) + double-submit CSRF token; rate limits |
| Automation → API | API | client | personal access tokens (`isc_pat_`, stored hashed, revocable, optional expiry) |
| Webhooks → triggers | API | sender | HMAC-SHA256 over `timestamp.body`, 5-minute window, single-use signatures (or a shared token) |
| Model output → tools | harness | model | tools are allowlisted per agent; policies can deny or require approval; budgets bound calls |
| Tools → network | harness | internet / internal network | SSRF guard (below) |
| Generated code → host | host | code | [sandbox](sandbox.md) |
| Account → account | API | other accounts | workspace membership checked on every endpoint; cross-workspace access returns 404 |

## Secrets

Provider keys come from environment variables (shared by the installation) or from **Keys & secrets** (encrypted with
Fernet, per workspace). They are resolved server-side at call time, never returned by any API, never written to workflow
JSON or exports (`strip_secrets`), and redacted from node traces and logs. HTTP tool headers reference secrets as
`{{secret:name}}`. Installation secrets are generated on first start into the `secrets` volume (mode 0600) unless set.

## HTTP tool and SSRF

The HTTP tool (and MCP endpoints and provider base URLs) accept only `http`/`https` and block: loopback, private
(RFC 1918, ULA), link-local (incl. `169.254.169.254`), CGNAT `100.64.0.0/10`, multicast, reserved and unspecified
addresses, IPv4-mapped IPv6 forms of those, cloud metadata names and addresses (`metadata.google.internal`,
`fd00:ec2::254`, `100.100.100.200`, ...), `localhost`, `*.localhost` and `*.internal`. Every resolved address must
pass; decimal/hex/octal IP spellings are resolved and checked. Redirects are followed manually (max 5) and each hop is
re-checked. **DNS pinning:** the HTTP tool connects to the exact address that was checked (Host header and TLS SNI keep
the original name), so a rebinding DNS server cannot switch to an internal address after the check. Responses are
capped at 1 MB. Administrators can allow specific private hosts with `ISOCLINE_ALLOW_PRIVATE_NETWORK_HOSTS`
(per host; never a global off switch). Tests: `apps/api/tests/security/test_ssrf.py`.

Known gap: the MCP client checks its endpoint but does not pin DNS.

## Uploads

Size-limited (`ISOCLINE_MAX_UPLOAD_MB`, 25), stored under generated keys (never user-supplied paths); text is
extracted in the worker (PDF, DOCX, text formats). Downloads use `Content-Disposition: attachment`. Uploaded content is
treated as untrusted input to models (prompt injection is a model-level risk; tools and approvals are the control).

## Local deployment assumptions

Defaults assume a single-tenant, self-hosted installation: ports on 127.0.0.1, sign-up closed after the first account,
the test provider enabled, no TLS. Before exposing it, follow [self-hosting.md](self-hosting.md#exposing-an-installation).

No certification or compliance claim is made. Report vulnerabilities per [SECURITY.md](../SECURITY.md).
