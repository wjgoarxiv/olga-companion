"""A pipe LENGTH and its LSEGMENT list may use different length units; the check compares lengths."""
from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import genkey_static

FIXTURES = Path(__file__).parent / "fixtures"


def _x012(tmp_path: Path, pipe: str) -> list[str]:
    text = f'''OPTIONS TEMPERATURE=ADIABATIC
NETWORKCOMPONENT TYPE=FLOWPATH, TAG=FLOWPATH_1
 PARAMETERS LABEL=LINE
 GEOMETRY LABEL="G"
 PIPE ROUGHNESS=5E-05 m, LABEL="P1", WALL=W, NSEGMENT=2, {pipe}, ELEVATION=0 mm, DIAMETER=53.5 mm
ENDNETWORKCOMPONENT
ENDCASE
'''
    case = tmp_path / "c.genkey"
    case.write_text(text, encoding="utf-8")
    report = genkey_static.run_tool("validator", [str(case)]).stdout
    assert "Validation Report" in report
    return [line for line in report.splitlines() if "X012" in line]


@pytest.mark.parametrize(
    "pipe",
    [
        "LSEGMENT=(0.104309, 0.074691) m, LENGTH=179 mm",
        "LSEGMENT=(104.309, 74.691) mm, LENGTH=0.179 M",
        "LSEGMENT=(0.5, 0.5) km, LENGTH=1000 m",
        "LSEGMENT=(50, 50), LENGTH=100 m",
        "LSEGMENT=(50, 50) ft, LENGTH=100 ft",
        "LSEGMENT=(50, 50) ft, LENGTH=30.48 m",
        "LSEGMENT=(50, 50) furlong, LENGTH=20117 m",
    ],
)
def test_the_same_length_in_two_units_is_accepted(tmp_path: Path, pipe: str) -> None:
    assert _x012(tmp_path, pipe) == []


@pytest.mark.parametrize(
    "pipe",
    [
        "LSEGMENT=(0.104309, 0.074691) m, LENGTH=190 mm",
        "LSEGMENT=(50, 50) m, LENGTH=100 mm",
        "LSEGMENT=(50, 50) m, LENGTH=100 ft",
        "LSEGMENT=(50, 50) m, LENGTH=120 m",
        "LSEGMENT=(50, 50), LENGTH=120",
    ],
)
def test_a_real_mismatch_is_still_an_error(tmp_path: Path, pipe: str) -> None:
    assert len(_x012(tmp_path, pipe)) == 1


def test_the_message_gives_both_lengths_in_one_unit(tmp_path: Path) -> None:
    (line,) = _x012(tmp_path, "LSEGMENT=(0.104309, 0.074691) m, LENGTH=190 mm")
    assert "LENGTH=0.19 m" in line and "sum is 0.179 m" in line
