"""Role-based access control (server-side). Permissions are "<resource>:<action>".

Built-in roles, per workspace: owner, admin, developer, operator, reviewer, viewer. Role names used by older checks
("viewer" / "editor" / "admin" / "owner") map onto permissions, so every endpoint is enforced through one matrix."""
from __future__ import annotations

RESOURCES = ["agents", "workflows", "secrets", "policies", "approvals", "audit", "workspace"]

_READ_ALL = [f"{r}:read" for r in RESOURCES if r != "audit"]

BUILTIN_ROLES: dict[str, dict] = {
    "viewer": {"label": "Viewer", "description": "Read workflows, agents, runs and results.", "permissions": _READ_ALL},
    "reviewer": {"label": "Reviewer", "description": "Viewer + decide approvals and read the audit log.",
                 "permissions": _READ_ALL + ["approvals:decide", "audit:read"]},
    "operator": {"label": "Operator", "description": "Run and operate: execute workflows, manage triggers, decide approvals.",
                 "permissions": _READ_ALL + ["workflows:execute", "workflows:operate", "approvals:decide", "secrets:use"]},
    "developer": {"label": "Developer", "description": "Build: edit and publish agents and workflows; run them.",
                  "permissions": _READ_ALL + [f"{r}:{a}" for r in ("agents", "workflows") for a in ("write", "publish", "execute")]
                  + ["workflows:operate", "secrets:use"]},
    "admin": {"label": "Admin", "description": "Everything except transferring ownership.", "permissions": ["*"]},
    "owner": {"label": "Owner", "description": "Full control of the workspace.", "permissions": ["*"]},
}
LEGACY_ALIASES = {"editor": "developer"}
ADMIN_ONLY = {"workspace:owner"}  # never granted by "*" on admin
LEGACY_REQUIREMENT = {"viewer": "workspace:read", "editor": "workflows:write", "admin": "workspace:manage", "owner": "workspace:owner"}
ALL_PERMISSIONS = sorted({f"{r}:{a}" for r in RESOURCES for a in ("read", "write", "publish", "execute", "decide", "manage", "use")})


def role_permissions(role: str, custom: dict[str, list[str]] | None = None) -> set[str]:
    role = LEGACY_ALIASES.get(role, role)
    if role in BUILTIN_ROLES:
        perms = set(BUILTIN_ROLES[role]["permissions"])
        if role == "owner":
            perms |= ADMIN_ONLY
        return perms
    return set((custom or {}).get(role, []))


def allowed(perms: set[str], required: str) -> bool:
    required = LEGACY_REQUIREMENT.get(required, required)
    if required in perms:
        return True
    if required in ADMIN_ONLY:
        return False
    if "*" in perms:
        return True
    res, _, act = required.partition(":")
    return f"{res}:*" in perms or (act == "read" and "*:read" in perms)
