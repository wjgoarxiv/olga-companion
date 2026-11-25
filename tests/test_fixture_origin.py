"""Files in this repository are written by hand or by the app, not copied from OLGA or Multiflash output."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"
VENDOR_MARKS = (
    b"Multiflash Version 7",  # the header Multiflash writes into a table
    b"DELIVERED BY",  # OLGA's own start page
    b"customercarecenter",
    b"'OLGA 2022.1.0.35696'",  # the build an OLGA run writes into a result file
    b"CPU CORES USED",
)


def _files() -> list[Path]:
    return sorted(path for root in (FIXTURES, REPO / "resources" / "fluids") for path in root.rglob("*") if path.is_file())


@pytest.mark.parametrize("path", _files(), ids=lambda path: path.relative_to(REPO).as_posix())
def test_a_fixture_carries_no_vendor_output(path: Path) -> None:
    content = path.read_bytes()
    assert [mark for mark in VENDOR_MARKS if mark in content] == []


def test_no_vendor_key_text_is_kept() -> None:
    assert not (REPO / "resources" / "olga-vendor").exists()
