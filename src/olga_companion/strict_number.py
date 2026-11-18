"""One reader for numbers a person types or pastes: plain decimals only, ambiguous text refused.

Accepted: an optional sign, digits with one optional decimal point, an optional exponent
("-1.5", ".5", "2e5"). With ``decimal_comma`` a single comma is a decimal point ("0,05").
Refused, never guessed: "1,500" (a thousands group or 1.5?), "1.234,5", "1_000", "0x10",
"nan", "inf", inner spaces, and anything else. The frontend reads the same way
(frontend/src/strictNumber.mjs); tests/fixtures/strict_number_cases.json holds both.
"""
from __future__ import annotations

import math
import re
from typing import Final

_PLAIN: Final = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", re.ASCII)
_COMMA: Final = re.compile(r"[-+]?(?:\d+,\d+|,\d+)(?:[eE][-+]?\d+)?", re.ASCII)
_THOUSANDS: Final = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+", re.ASCII)


def parse_number(value: object, *, decimal_comma: bool = True) -> float | None:
    """The finite number the text plainly says, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _PLAIN.fullmatch(text):
        number = float(text)
    elif decimal_comma and _COMMA.fullmatch(text) and not _THOUSANDS.fullmatch(text):
        number = float(text.replace(",", "."))
    else:
        return None
    return number if math.isfinite(number) else None
