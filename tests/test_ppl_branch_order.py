"""A .ppl lists its branches in file order, the same on every start (review 2026-11-27).

The app opens a profile result on `branches[0]` and the CLI uses `list_branches()[0]` when no
branch is named, so a hash-seed-dependent order opened a different branch each session.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "resources" / "olga-toolkit" / "scripts"

PPL = (
    "'OLGA 2022.1.0'\n"
    "PROFILE PLOT\n"
    "GEOMETRY ' (M)  '\n"
    "BRANCH\n'LINE_3-10'\n3\n0.0 50.0 100.0\n0.0 1.0 2.0\n"
    "BRANCH\n'LINE_3'\n3\n0.0 50.0 100.0\n0.0 1.0 2.0\n"
    "BRANCH\n'RISER'\n3\n0.0 50.0 100.0\n0.0 1.0 2.0\n"
    "CATALOG\n4\n"
    "PT 'BOUNDARY:' 'BRANCH:' 'LINE_3-10' '(PA)' 'Pressure'\n"
    "PT 'BOUNDARY:' 'BRANCH:' 'LINE_3' '(PA)' 'Pressure'\n"
    "PT 'BOUNDARY:' 'BRANCH:' 'RISER' '(PA)' 'Pressure'\n"
    "TM 'BOUNDARY:' '(C)' 'Temperature without a branch'\n"
    "TIME SERIES  ' (S)  '\n"
    "0.0\n1.0 2.0 3.0\n4.0 5.0 6.0\n7.0 8.0 9.0\n10.0 11.0 12.0\n"
    "10.0\n1.5 2.5 3.5\n4.5 5.5 6.5\n7.5 8.5 9.5\n10.5 11.5 12.5\n"
)

PROBE = """
import json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import result_parser
print(json.dumps(result_parser.ResultParser(sys.argv[2]).list_branches()))
"""


def _branches(path: Path, seed: str) -> list:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    done = subprocess.run(
        [sys.executable, "-c", PROBE, str(SCRIPTS), str(path)], capture_output=True, text=True, env=env, timeout=120
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("seed", ["0", "1", "3", "7"])
def test_branches_come_in_file_order_whatever_the_hash_seed(tmp_path: Path, seed: str):
    path = tmp_path / "case.ppl"
    path.write_text(PPL)
    assert _branches(path, seed) == ["LINE_3-10", "LINE_3", "RISER"]
