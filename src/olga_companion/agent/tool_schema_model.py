"""One typed tool declaration shared by provider and dispatch surfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .tool_schema_catalog import closed_schema

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class Tool:
    """One allowlisted tool declaration and its server-side handler."""

    __slots__ = (
        "name",
        "description",
        "parameters",
        "handler",
        "side_effect",
        "response_schema",
    )

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
        side_effect: bool = False,
        response_schema: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.side_effect = side_effect
        self.response_schema = response_schema


def schema(props: dict[str, str], required: list[str]) -> dict[str, Any]:
    """Return a closed compatibility schema for primitive-only callers."""
    return closed_schema(props, required)
