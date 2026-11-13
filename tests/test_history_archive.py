from __future__ import annotations

from pathlib import Path

from olga_companion.agent import history, history_archive


def test_archive_plan_classifies_empty_and_explicit_qa_sessions(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    empty = history.new_session("")
    qa = history.new_session("[QA] navigation")
    history.append(qa, {"record": "user", "text": "fixture check", "qa_session": True})
    real = history.new_session("Engineering review")
    history.append(real, {"record": "user", "text": "Review the current case."})

    plan = history_archive.build_archive_plan()

    by_id = {item.session_id: item.reason for item in plan.items}
    assert by_id[empty] == "metadata-only"
    assert by_id[qa] == "explicit-qa"
    assert real not in by_id


def test_archive_manifest_is_hash_bound_and_restorable(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    session_id = history.new_session("")
    plan = history_archive.build_archive_plan()

    receipt = history_archive.apply_archive_plan(plan, archive_id="archive-test")

    assert receipt.moved == 1
    assert not (history.chats_root() / f"{session_id}.jsonl").exists()
    restored = history_archive.restore_archive(receipt.manifest_path)
    assert restored == 1
    assert history.read(session_id)[0]["record"] == "meta"
