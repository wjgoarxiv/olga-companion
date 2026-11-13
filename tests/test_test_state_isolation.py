from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_pytest_does_not_clear_inherited_application_approval_records(tmp_path: Path) -> None:
    owner = tmp_path / "owner-app"
    journal = owner / "var" / "approval-journal"
    journal.mkdir(parents=True)
    marker = journal / ("a" * 32 + ".json")
    marker.write_text('{"owner_record":true}', encoding="utf-8")
    process = subprocess.run(
        [
            sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "tests/test_pending_approvals.py::test_pending_approval_is_exact_bound_and_one_shot",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        env={
            **os.environ,
            "OLGA_APP_DATA_DIR": str(owner),
            "OLGA_APPROVAL_JOURNAL_DIR": str(journal),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert marker.is_file(), "pytest cleared an inherited application's approval journal"
    assert marker.read_text(encoding="utf-8") == '{"owner_record":true}'
    assert sorted(journal.iterdir()) == [marker]
