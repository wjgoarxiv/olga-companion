"""Small deterministic validator for the JSON Schema subset used by tools."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SchemaValidationError(ValueError):
    """One model tool input violated its declared JSON Schema."""

    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}: {self.reason}"


def _type_matches(expected: str, value: Any) -> bool:
    match expected:
        case "object":
            return isinstance(value, dict)
        case "array":
            return isinstance(value, list)
        case "string":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        case "boolean":
            return isinstance(value, bool)
        case "null":
            return value is None
        case _:
            return False


def _expected_types(schema: dict[str, Any]) -> list[str]:
    expected = schema.get("type")
    if isinstance(expected, str):
        return [expected]
    if isinstance(expected, list) and all(isinstance(item, str) for item in expected):
        return expected
    return []


def _first_violation(
    schema: dict[str, Any],
    value: Any,
    path: str,
) -> SchemaValidationError | None:
    expected_types = _expected_types(schema)
    if expected_types and not any(_type_matches(expected, value) for expected in expected_types):
        return SchemaValidationError(path, f"expected type {' or '.join(expected_types)}")
    if "const" in schema and value != schema["const"]:
        return SchemaValidationError(path, f"must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        return SchemaValidationError(path, f"value is outside enum {schema['enum']!r}")

    for branch in schema.get("allOf", []):
        condition = branch.get("if")
        if condition is None:
            violation = _first_violation(branch, value, path)
        elif _first_violation(condition, value, path) is None:
            violation = _first_violation(branch.get("then", {}), value, path)
        else:
            violation = _first_violation(branch.get("else", {}), value, path)
        if violation is not None:
            return violation

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                return SchemaValidationError(path, f"required field {name!r} is missing")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                return SchemaValidationError(path, f"unknown additional field {unknown[0]!r}")
        for name, item in value.items():
            child_schema = properties.get(name)
            if child_schema is not None:
                violation = _first_violation(child_schema, item, f"{path}.{name}")
                if violation is not None:
                    return violation

    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            return SchemaValidationError(path, f"has fewer than {schema['minItems']} items")
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and len(value) > maximum:
            return SchemaValidationError(path, f"has more than maximum {maximum} items")
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if item in value[:index]:
                    return SchemaValidationError(path, "items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                violation = _first_violation(item_schema, item, f"{path}[{index}]")
                if violation is not None:
                    return violation

    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            return SchemaValidationError(path, f"is shorter than {schema['minLength']} characters")
        maximum = schema.get("maxLength")
        if isinstance(maximum, int) and len(value) > maximum:
            return SchemaValidationError(path, f"is longer than maximum {maximum} characters")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            return SchemaValidationError(path, f"does not match pattern {pattern!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            return SchemaValidationError(path, "must be finite")
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and number < minimum:
            return SchemaValidationError(path, f"is below minimum {minimum}")
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and number > maximum:
            return SchemaValidationError(path, f"is above maximum {maximum}")
    return None


def validate_json_schema(schema: dict[str, Any], value: Any) -> None:
    """Raise the first deterministic validation error for ``value``."""
    violation = _first_violation(schema, value, "$")
    if violation is not None:
        raise violation
