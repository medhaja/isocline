"""Common tool interface. Permissions are enforced by the agent runtime, never by model output."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


class ToolError(Exception):
    pass


@dataclass
class ToolContext:
    workspace_id: str
    project_id: str
    run_id: str | None
    get_secret: Callable[[str], Awaitable[str | None]]  # provider/name -> decrypted value (server-side only)
    knowledge_base_ids: list[str] = field(default_factory=list)
    secret_values: list[str] = field(default_factory=list)  # values to redact from recorded output
    open_session: Callable[[], Any] | None = None  # async context manager yielding an AsyncSession


class Tool:
    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    permissions: list[str] = []  # informational: network, code_execution, filesystem, knowledge

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> Any:
        raise NotImplementedError
