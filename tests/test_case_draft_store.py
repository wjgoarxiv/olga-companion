"""Private, expiring, revision-checked storage for imported case drafts."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from olga_companion import case_draft_store as store

SPEC = {"version": "3", "nodes": []}


@pytest.fixture(autouse=True)
def _private_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "drafts"
    monkeypatch.setenv("OLGA_CASE_DRAFT_DIR", str(root))
    return root


def _create(now: float = 1000.0, generation: int = 3, **extra):
    return store.create_draft(
        context_generation=generation, source_name="pipes.csv", spec=SPEC,
        summary={"flowpaths": 1}, label_map={"flowpaths": {}}, options={"max_section_m": 1.0},
        now=now, **extra,
    )


def test_create_get_update_round_trip() -> None:
    draft = _create()
    loaded = store.get_draft(draft.draft_id, context_generation=3, now=1001.0)
    assert loaded == draft and loaded.revision == 1

    updated = store.update_draft(
        draft.draft_id, revision=1, context_generation=3, spec={"version": "3", "nodes": [1]},
        summary={"flowpaths": 2}, now=1002.0,
    )
    assert updated.revision == 2 and updated.spec == {"version": "3", "nodes": [1]}
    assert store.get_draft(draft.draft_id, context_generation=3, now=1003.0).summary == {"flowpaths": 2}


def test_an_expired_draft_is_refused() -> None:
    draft = _create(now=1000.0)
    with pytest.raises(store.DraftError, match="expired"):
        store.get_draft(draft.draft_id, context_generation=3, now=1000.0 + store.DRAFT_TTL_SECONDS + 1)


def test_another_workspace_generation_is_refused() -> None:
    draft = _create(generation=3)
    with pytest.raises(store.DraftError, match="workspace"):
        store.get_draft(draft.draft_id, context_generation=4, now=1001.0)


def test_a_stale_revision_is_refused() -> None:
    draft = _create()
    store.update_draft(draft.draft_id, revision=1, context_generation=3, spec=SPEC, summary={}, now=1001.0)
    with pytest.raises(store.DraftError, match="changed"):
        store.update_draft(draft.draft_id, revision=1, context_generation=3, spec=SPEC, summary={}, now=1002.0)


def test_old_drafts_are_pruned_past_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "MAX_DRAFTS", 3)
    drafts = [_create(now=1000.0 + index) for index in range(5)]
    kept = sorted(path.stem for path in store._root().glob("*.json"))
    assert kept == sorted(draft.draft_id for draft in drafts[-3:])
    with pytest.raises(store.DraftError, match="not found"):
        store.get_draft(drafts[0].draft_id, context_generation=3, now=1010.0)


def test_expired_drafts_are_pruned_on_create() -> None:
    old = _create(now=1000.0)
    _create(now=1000.0 + store.DRAFT_TTL_SECONDS + 5)
    assert not (store._root() / f"{old.draft_id}.json").exists()


def test_an_oversize_draft_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "MAX_DRAFT_BYTES", 100)
    with pytest.raises(store.DraftError, match="too large"):
        store.create_draft(
            context_generation=0, source_name="x.csv", spec={"pad": "x" * 200}, summary={},
            label_map={}, options={}, now=1.0,
        )


@pytest.mark.parametrize("draft_id", ["../escape", "A" * 32, "", "0" * 31])
def test_malformed_ids_are_refused(draft_id: str) -> None:
    with pytest.raises(store.DraftError):
        store.get_draft(draft_id, context_generation=0, now=1.0)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_drafts_are_private_on_posix() -> None:
    draft = _create()
    path = store._root() / f"{draft.draft_id}.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(store._root()).st_mode) == 0o700


def test_pruning_never_touches_files_that_are_not_drafts(_private_root: Path) -> None:
    _private_root.mkdir(parents=True, exist_ok=True)
    notes = _private_root / "notes.json"
    notes.write_text("{}", encoding="utf-8")
    _create()
    assert notes.exists()


def test_stale_tmp_files_are_pruned_on_create(_private_root: Path) -> None:
    # A crashed writer can leave a .draft-*.tmp behind; the next create must
    # clear ones older than the draft TTL but keep a fresh one in flight.
    _private_root.mkdir(parents=True, exist_ok=True)
    now = 2000.0
    stale = _private_root / ".draft-abc123.tmp"
    stale.write_bytes(b"{}")
    os.utime(stale, (now - store.DRAFT_TTL_SECONDS - 1, now - store.DRAFT_TTL_SECONDS - 1))
    fresh = _private_root / ".draft-fresh.tmp"
    fresh.write_bytes(b"{}")
    os.utime(fresh, (now, now))
    _create(now=now)
    assert not stale.exists()
    assert fresh.exists()


def test_delete() -> None:
    draft = _create()
    store.delete_draft(draft.draft_id)
    with pytest.raises(store.DraftError, match="not found"):
        store.get_draft(draft.draft_id, context_generation=3, now=1001.0)
