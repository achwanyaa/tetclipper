"""Validate a clip spec against spec.schema.json.

The schema is generated from the zod definition in
studio/composition/src/spec.ts (`npm run schema`), so Python, the editor and
Claude Code all check the same contract. It only uses a small JSON Schema
subset (type, properties, required, additionalProperties, items, enum,
const, minimum/maximum, exclusiveMinimum, anyOf), which this validator
covers without pulling in a dependency.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("spec.schema.json")

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


@lru_cache(maxsize=1)
def schema() -> dict:
    doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return doc["definitions"]["ClipSpec"]


def _is_type(value, name: str) -> bool:
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def _check(value, node: dict, path: str, errors: list[str]) -> None:
    if "anyOf" in node:
        for option in node["anyOf"]:
            trial: list[str] = []
            _check(value, option, path, trial)
            if not trial:
                return
        # Report the closest option for a discriminated union (same "type" const).
        if isinstance(value, dict) and "type" in value:
            for option in node["anyOf"]:
                const = option.get("properties", {}).get("type", {}).get("const")
                if const == value["type"]:
                    _check(value, option, path, errors)
                    return
        errors.append(f"{path}: doesn't match any allowed shape")
        return
    kind = node.get("type")
    if kind is not None:
        kinds = kind if isinstance(kind, list) else [kind]
        if not any(_is_type(value, k) for k in kinds):
            errors.append(f"{path}: expected {' or '.join(kinds)}, got {type(value).__name__}")
            return
    if "const" in node and value != node["const"]:
        errors.append(f"{path}: must be {node['const']!r}")
    if "enum" in node and value not in node["enum"]:
        errors.append(f"{path}: must be one of {', '.join(map(str, node['enum']))}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in node and value < node["minimum"]:
            errors.append(f"{path}: must be >= {node['minimum']}")
        if "maximum" in node and value > node["maximum"]:
            errors.append(f"{path}: must be <= {node['maximum']}")
        if "exclusiveMinimum" in node and value <= node["exclusiveMinimum"]:
            errors.append(f"{path}: must be > {node['exclusiveMinimum']}")
    if isinstance(value, dict):
        props = node.get("properties", {})
        for key in node.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        for key, item in value.items():
            if key in props:
                _check(item, props[key], f"{path}.{key}", errors)
            elif node.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: unknown field")
    if isinstance(value, list) and "items" in node:
        for i, item in enumerate(value):
            _check(item, node["items"], f"{path}[{i}]", errors)


def validate(spec) -> list[str]:
    """Every problem with `spec`, as 'path: message' strings (empty = valid)."""
    errors: list[str] = []
    _check(spec, schema(), "spec", errors)
    if isinstance(spec, dict) and isinstance(spec.get("source"), dict):
        src = spec["source"]
        if isinstance(src.get("start"), (int, float)) and isinstance(src.get("end"), (int, float)):
            if src["end"] <= src["start"]:
                errors.append("spec.source: end must be after start")
    return errors[:50]
