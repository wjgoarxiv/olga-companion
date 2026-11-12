"""genkey_review carries the server file hash that case_edit_plan already checks."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from olga_companion.agent import approvals, pending_approvals, tools

_FIXTURE = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"
_HASH = re.compile(r"^[0-9a-f]{64}$")


def _owner_text() -> str:
    text = _FIXTURE.read_text(encoding="utf-8")
    return text.replace("ENDTIME=24 h", "ENDTIME=900 s", 1)


@pytest.fixture(autouse=True)
def _clear_capabilities() -> None:
    approvals.revoke_all()
    pending_approvals.revoke_all()
    yield
    approvals.revoke_all()
    pending_approvals.revoke_all()


def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    source = root / "owner.genkey"
    source.write_text(_owner_text(), encoding="utf-8")
    (root / "dummy_fluid.tab").write_text('PVTTABLE LABEL="FLUID-A"\n', encoding="utf-8")
    return source


def test_review_hash_plans_that_source_and_rejects_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _workspace(tmp_path, monkeypatch)
    before = source.read_bytes()
    digest = hashlib.sha256(before).hexdigest()

    review = tools.dispatch("genkey_review", {"path": str(source)})

    assert review["source_sha256"] == digest
    assert _HASH.fullmatch(review["source_sha256"])
    assert review["validation"]["source_sha256"] == digest
    assert review["summary"]["source_sha256"] == digest
    assert source.read_bytes() == before

    plan = tools.dispatch(
        "case_edit_plan",
        {
            "source": str(source),
            "source_hash": review["source_sha256"],
            "operations": [{"op": "set_integration", "end_time_s": 60}],
        },
    )
    assert plan["publishable"] is True
    assert plan["source_hash"] == digest
    assert source.read_bytes() == before

    other = ("0" if digest[0] != "0" else "1") * 64
    with pytest.raises(tools.ToolError, match="stale"):
        tools.dispatch(
            "case_edit_plan",
            {
                "source": str(source),
                "source_hash": other,
                "operations": [{"op": "set_integration", "end_time_s": 60}],
            },
        )
    assert source.read_bytes() == before
