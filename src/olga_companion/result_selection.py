from __future__ import annotations

import re
from typing import Final

from .genkey_static import OlgaInputError

NAME_TOKEN: Final = re.compile(r"^[A-Za-z0-9_\-]+$")


def require_tokens(values: list[str], what: str) -> list[str]:
    if not values:
        raise OlgaInputError(f"At least one {what} is required.")
    for value in values:
        if not NAME_TOKEN.fullmatch(value) or value.startswith("-"):
            raise OlgaInputError(f"Invalid {what} name: {value!r}")
    return values


def positions_equivalent(selector: str, returned: str) -> bool:
    components = selector.split(" - ")
    if len(components) == 2 and components[0].casefold() in {"branch", "br"}:
        return components[1].casefold() == returned.casefold()
    if len(components) == 1 or components[0].casefold() != "section":
        return selector.casefold() == returned.casefold()
    fields = components[1:]
    if not fields or len(fields) % 2 or any(not field for field in fields):
        return False
    pairs = list(zip(fields[::2], fields[1::2], strict=True))
    branches = [value for key, value in pairs if key.casefold() == "br"]
    if len(branches) != 1:
        return False
    branch = branches[0]
    if not NAME_TOKEN.fullmatch(branch) or branch.startswith("-"):
        return False
    return branch.casefold() == returned.casefold()
