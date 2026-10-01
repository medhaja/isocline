"""Structured outputs: schema normalization, parsing and validation. Invalid data never propagates."""
from __future__ import annotations

import json
import re

import jsonschema

_SIMPLE = {"string": "string", "number": "number", "integer": "integer", "boolean": "boolean",
           "array": "array", "object": "object", "str": "string", "int": "integer", "float": "number", "bool": "boolean"}


class StructuredOutputError(Exception):
    def __init__(self, message: str, raw: str | None = None, errors: list[str] | None = None):
        super().__init__(message)
        self.raw = raw
        self.errors = errors or []


_JSON_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}
_SCHEMA_KEYS = {"type", "description", "enum", "minimum", "maximum", "format", "title", "default"}


def is_json_schema(schema: dict) -> bool:
    if any(k in schema for k in ("properties", "$schema", "items", "anyOf", "oneOf", "allOf", "$ref")):
        return True
    t = schema.get("type")
    return isinstance(t, str) and t in _JSON_TYPES and set(schema) <= _SCHEMA_KEYS


def normalize_schema(schema: dict | None) -> dict | None:
    """Accepts full JSON Schema or the simple form {"field": "type"} and returns JSON Schema."""
    if not schema:
        return None
    if is_json_schema(schema):
        return schema
    props: dict = {}
    for k, v in schema.items():
        if isinstance(v, str):
            t = v.rstrip("?").lower()
            if t.endswith("[]"):
                props[k] = {"type": "array", "items": {"type": _SIMPLE.get(t[:-2], "string")}}
            else:
                props[k] = {"type": _SIMPLE.get(t, "string")}
        elif isinstance(v, dict):
            props[k] = normalize_schema(v) if "type" not in v else v
        elif isinstance(v, list) and v:
            props[k] = {"type": "array", "items": normalize_schema(v[0]) if isinstance(v[0], dict) else {"type": _SIMPLE.get(str(v[0]), "string")}}
    required = [k for k, v in schema.items() if not (isinstance(v, str) and v.endswith("?"))]
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str):
    t = (text or "").strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    m = _FENCE.search(t)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except ValueError:
            pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        s, e = t.find(open_c), t.rfind(close_c)
        if s != -1 and e > s:
            try:
                return json.loads(t[s:e + 1])
            except ValueError:
                continue
    raise StructuredOutputError("Output is not valid JSON", raw=text[:2000])


def validate(data, schema: dict) -> list[str]:
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in sorted(v.iter_errors(data), key=str)][:10]


def parse_and_validate(text: str, structured, schema: dict):
    data = structured if structured is not None else extract_json(text)
    errs = validate(data, schema)
    if errs:
        raise StructuredOutputError("Output does not match the schema", raw=json.dumps(data)[:2000] if not isinstance(data, str) else data, errors=errs)
    return data
