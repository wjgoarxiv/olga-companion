"""Contained PVT companion verification for CaseSpec preview contexts."""

from __future__ import annotations

import re
from pathlib import Path

UNVERIFIED_WARNING = (
    "PVT companion existence is verified only in a contained publish context."
)
PENDING_WARNING = (
    "The PVT table does not exist yet; an approved earlier plan step must create it, and "
    "publishing checks it again."
)


# The toolkit resolves FLUID against this header token (genkey_builder._resolve_fluid_label).
_PVT_LABEL = re.compile(r'PVTTABLE\s+LABEL\s*=\s*"?([^",\s]+)"?', re.IGNORECASE)
_HEADER_BYTES = 262_144


class CompanionVerificationError(ValueError):
    """A referenced PVT companion is missing, leaves the owner directory, or has another label."""


def _declared_label(table: Path) -> str | None:
    with table.open("rb") as stream:
        header = stream.read(_HEADER_BYTES).decode("utf-8", errors="replace")
    found = _PVT_LABEL.search(header)
    return found[1] if found else None


def verify_pvt_companion(
    owner: Path | None,
    reference: str,
    fluid_label: str | None = None,
    *,
    pending: str | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Verify a relative .tab beside a contained owner when context is available.

    With ``fluid_label`` the table's own ``PVTTABLE LABEL`` must match it: OLGA
    resolves ``FLUID`` against that label, so a mismatch fails at the solver.
    ``pending`` names the one reference that a plan step will create: while that file is
    still absent it is neither checked nor verified. An existing file is always checked.
    """
    if owner is None:
        return "unverified", (UNVERIFIED_WARNING,)
    root = owner.parent.resolve()
    candidate = (root / reference).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CompanionVerificationError("PVT companion escapes the owner directory.") from exc
    if pending is not None and reference == pending and candidate.suffix.casefold() == ".tab" and not candidate.exists():
        return "unverified", (PENDING_WARNING,)
    if candidate.suffix.casefold() != ".tab" or not candidate.is_file():
        raise CompanionVerificationError("Referenced PVT companion is missing.")
    if fluid_label is not None:
        declared = _declared_label(candidate)
        if declared != fluid_label:
            raise CompanionVerificationError(
                f"PVT table label is {declared[:64]!r}, not the requested fluid label "
                f"{fluid_label!r}; use the label stored inside the .tab file."
                if declared
                else "The PVT table declares no PVTTABLE LABEL, so no fluid label can be verified."
            )
    return "verified", ()
