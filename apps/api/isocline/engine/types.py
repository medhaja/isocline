"""Typed ports & edges.

Type expressions: Text | Number | Boolean | JSON | JSON<T> | Table | File | Image | Audio | Video | Document |
Message | Message[] | Artifact | Artifact<kind> | Error | Any | <CustomTypeName> (a workspace JSON Schema, = JSON<Name>).

Compatibility is decided structurally when schemas are available. Data is never converted silently: when a
conversion exists, the checker returns a *suggestion* (e.g. insert a CSV → Table transform) and the edge stays
invalid until the user accepts it."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from isocline.engine.structured import normalize_schema, validate

BUILTIN = {"Text", "Number", "Boolean", "JSON", "Table", "File", "Image", "Audio", "Video", "Document", "Message",
           "Message[]", "Artifact", "Error", "Any"}
_GENERIC = re.compile(r"^(JSON|Artifact)<([A-Za-z0-9_\-]+)>$")
ARTIFACT_KIND_TO_TYPE = {"csv": "File", "pdf": "Document", "docx": "Document", "txt": "Document", "md": "Document",
                         "image": "Image", "png": "Image", "jpg": "Image", "json": "File", "table": "Table"}


@dataclass(frozen=True)
class TypeRef:
    base: str  # a BUILTIN name
    arg: str | None = None  # JSON<arg> / Artifact<arg>

    def __str__(self) -> str:
        return f"{self.base}<{self.arg}>" if self.arg else self.base


class TypeError_(ValueError):
    pass


def parse_type(expr: str | None, custom: dict[str, dict] | None = None) -> TypeRef:
    expr = (expr or "Any").strip()
    if expr in BUILTIN:
        return TypeRef(expr)
    m = _GENERIC.match(expr)
    if m:
        base, arg = m.groups()
        if base == "JSON" and custom is not None and arg not in custom:
            raise TypeError_(f"Unknown type {arg}. Define it under Custom types first.")
        return TypeRef(base, arg)
    if custom is not None and expr in custom:
        return TypeRef("JSON", expr)
    raise TypeError_(f"Unknown type '{expr}'")


@dataclass
class Compat:
    ok: bool
    note: str = ""
    suggestion: dict | None = None  # {"transform": mode, "label": "..."} when a conversion exists


def _schema_for(t: TypeRef, custom: dict[str, dict]) -> dict | None:
    if t.base == "JSON" and t.arg:
        return normalize_schema(custom.get(t.arg)) if custom.get(t.arg) else None
    return None


def _schema_satisfies(src: dict, dst: dict) -> bool:
    """src (producer) guarantees every property dst requires, with compatible JSON types."""
    sp, dp = src.get("properties", {}), dst.get("properties", {})
    for req in dst.get("required", []):
        if req not in sp:
            return False
        st, dt = sp[req].get("type"), dp.get(req, {}).get("type")
        if dt and st and dt != st and not (dt == "number" and st == "integer"):
            return False
    return True


def compatible(src: TypeRef, dst: TypeRef, custom: dict[str, dict] | None = None) -> Compat:
    custom = custom or {}
    if dst.base == "Any" or src.base == "Any":
        return Compat(True)
    if src == dst:
        return Compat(True)
    # JSON family
    if dst.base == "JSON":
        if src.base == "JSON":
            if not dst.arg:
                return Compat(True)
            if not src.arg:
                return Compat(True, f"Unstructured JSON will be validated against {dst.arg} at runtime")
            ss, ds = _schema_for(src, custom), _schema_for(dst, custom)
            if ss is not None and ds is not None and _schema_satisfies(ss, ds):
                return Compat(True, f"{src.arg} provides every field {dst.arg} requires")
            return Compat(False, f"{src} does not provide the fields {dst} requires")
        if src.base == "Table":
            return Compat(True, "A table is a JSON list of rows")
        if src.base == "Text":
            return Compat(False, "Text is not JSON", {"transform": "json_parse", "label": "Insert Parse JSON transform"})
        return Compat(False, f"{src} is not JSON")
    if dst.base == "Text":
        if src.base in ("Number", "Boolean"):
            return Compat(True, "Formatted as text")
        if src.base in ("JSON", "Table"):
            return Compat(False, f"{src} is structured", {"transform": "to_text", "label": "Insert To text transform"})
        if src.base in ("Document", "Message"):
            return Compat(True)
        return Compat(False, f"{src} cannot be used as text")
    if dst.base == "Table":
        if src.base in ("File", "Document") or (src.base == "Artifact" and src.arg in ("csv", None)):
            return Compat(False, "Files must be parsed into a table", {"transform": "csv_to_table", "label": "Insert CSV → Table transform"})
        if src.base == "JSON" and not src.arg:
            return Compat(True, "Rows are validated at runtime")
        return Compat(False, f"{src} is not a table")
    if dst.base == "Artifact":
        if src.base == "Artifact":
            return Compat(dst.arg is None or src.arg == dst.arg, "" if dst.arg is None or src.arg == dst.arg else f"Expects a {dst.arg} artifact, got {src}")
        if src.base in ("File", "Document", "Image", "Audio", "Video"):
            return Compat(True, "Files travel as artifact references")
        return Compat(False, f"{src} is not an artifact")
    if dst.base in ("File", "Document", "Image", "Audio", "Video"):
        if src.base == "Artifact":
            if src.arg is None:
                return Compat(True, "Artifact kind is checked at runtime")
            return Compat(ARTIFACT_KIND_TO_TYPE.get(src.arg, "File") == dst.base or dst.base == "File",
                          "" if ARTIFACT_KIND_TO_TYPE.get(src.arg, "File") == dst.base or dst.base == "File" else f"A {src.arg} artifact is not {dst.base}")
        if dst.base == "Document" and src.base == "File":
            return Compat(True)
        return Compat(False, f"{src} is not {dst}")
    if dst.base == "Message[]" and src.base == "Message":
        return Compat(True, "Single message wrapped as a list")
    if dst.base == "Number" and src.base == "Text":
        return Compat(False, "Text is not a number", {"transform": "json_parse", "label": "Insert Parse JSON transform"})
    return Compat(False, f"{src} is not compatible with {dst}")


# ------------------------------------------------------------------------------------------ runtime checks
def check_value(value: Any, t: TypeRef, custom: dict[str, dict] | None = None) -> list[str]:
    """Runtime validation of a value against a port type. Returns error strings (empty = ok)."""
    custom = custom or {}
    b = t.base
    if b == "Any":
        return []
    if b == "Text":
        return [] if isinstance(value, str) else [f"expected Text, got {type(value).__name__}"]
    if b == "Number":
        return [] if isinstance(value, (int, float)) and not isinstance(value, bool) else [f"expected Number, got {type(value).__name__}"]
    if b == "Boolean":
        return [] if isinstance(value, bool) else [f"expected Boolean, got {type(value).__name__}"]
    if b == "JSON":
        if not isinstance(value, (dict, list)):
            return [f"expected JSON, got {type(value).__name__}"]
        schema = _schema_for(t, custom)
        return validate(value, schema) if schema else []
    if b == "Table":
        if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
            return ["expected Table (a list of row objects)"]
        return []
    if b in ("Artifact", "File", "Document", "Image", "Audio", "Video"):
        if is_artifact_ref(value):
            if b == "Artifact" and t.arg and value.get("type") != t.arg:
                return [f"expected a {t.arg} artifact, got {value.get('type')}"]
            return []
        if b in ("Document", "File") and isinstance(value, (str, dict)):
            return []  # V1 file input yields extracted text/document dicts
        return [f"expected {t}, got {type(value).__name__}"]
    if b == "Message":
        return [] if isinstance(value, dict) and "content" in value else ["expected a Message {role, content}"]
    if b == "Message[]":
        return [] if isinstance(value, list) and all(isinstance(m, dict) and "content" in m for m in value) else ["expected a list of messages"]
    if b == "Error":
        return [] if isinstance(value, dict) and "error" in value else ["expected an Error {error, kind}"]
    return []


def is_artifact_ref(v: Any) -> bool:
    return isinstance(v, dict) and isinstance(v.get("artifact_id"), str) and v.get("storage_uri") == "internal"


# ------------------------------------------------------------------------------------------ inferred port types
def default_output_type(node) -> str:
    """Output type of a node without an explicit contract. Conservative: when unsure, Any (never breaks V1)."""
    t, c = node.type, node.config or {}
    if node.contract and node.contract.output and node.contract.output.type:
        return node.contract.output.type
    if t == "agent":
        return "JSON" if c.get("output_schema") else "Text"
    if t == "input_text" or t == "input_url":
        return "Text"
    if t == "input_json":
        return "JSON"
    if t == "input_file":
        return "Artifact" if c.get("as_artifact") else "Document"
    if t == "input_chat":
        return "Message[]"
    if t.startswith("trigger_"):
        return "JSON"
    if t == "transform":
        return {"template": "Text", "to_text": "Text", "json_parse": "JSON", "mapping": "JSON", "csv_to_table": "Table"}.get(c.get("mode", "template"), "Any")
    if t in ("merge", "loop", "retry", "human_approval", "tool_web_search", "tool_http", "tool_python", "tool_json",
             "tool_vector_search", "tool_calculator", "wait_webhook", "wait_event", "subworkflow"):
        return "JSON"
    if t == "tool_file_reader":
        return "Document"
    return "Any"  # condition/router/parallel pass data through; outputs/annotations


def input_port_type(node, port: str | None) -> tuple[str, bool] | None:
    """(type, declared) for the input port an edge lands on. Only declared contracts are enforced."""
    if not node.contract or not node.contract.inputs:
        return None
    ports = {p.name: p for p in node.contract.inputs}
    if port and port in ports:
        return ports[port].type, True
    if len(ports) == 1:
        return next(iter(ports.values())).type, True
    return None
