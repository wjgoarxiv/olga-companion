"""Canonical Chat JSONL storage contracts for G002."""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from olga_companion.agent import history, history_listing


@pytest.fixture
def isolated_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    # Given: a history root isolated from persistent application sessions.
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    yield tmp_path


def test_append_canonicalizes_sequence_identity_and_nested_evidence(
    isolated_history: Path,
) -> None:
    # Given: nested evidence with credentials and deliberately oversized values.
    session_id = history.new_session("canonical")
    payload = {
        "record": "event",
        "type": "tool_result",
        "call_id": "call-1",
        "name": "results_load",
        "result": {
            "ok": True,
            "nested": {"authorization": "Bearer secret", "source": "case.ppl"},
            "values": list(range(300)),
            "log": "x" * 40_000,
        },
    }

    # When: evidence crosses the JSONL persistence boundary.
    history.append(session_id, payload)

    # Then: identity is canonical, credentials are absent, and evidence is bounded.
    records = history.read(session_id)
    assert [record["sequence"] for record in records] == [0, 1]
    assert all(record["schema_version"] == 1 for record in records)
    assert all(isinstance(record["record_id"], str) for record in records)
    result = records[1]["result"]
    assert result["nested"] == {"source": "case.ppl"}
    assert len(result["values"]) <= 128
    assert len(result["log"]) <= 16_384
    assert "secret" not in json.dumps(records)


def test_read_dedupes_retried_ids_and_legacy_double_assistant(
    isolated_history: Path,
) -> None:
    # Given: one retry-duplicated canonical record and an old text/done double-write.
    session_id = history.new_session("legacy")
    path = history.chats_root() / f"{session_id}.jsonl"
    lines = [
        {"schema_version": 1, "sequence": 1, "record_id": "same", "record": "user", "text": "hi"},
        {"schema_version": 1, "sequence": 1, "record_id": "same", "record": "user", "text": "hi"},
        {"record": "assistant", "text": "legacy answer"},
        {"record": "assistant", "text": "legacy answer"},
    ]
    with path.open("a", encoding="utf-8") as handle:
        handle.writelines(json.dumps(line) + "\n" for line in lines)

    # When: the mixed-version session is read.
    records = history.read(session_id)

    # Then: retries and the known legacy double-write are each represented once.
    assert [record.get("text") for record in records].count("hi") == 1
    assert [record.get("text") for record in records].count("legacy answer") == 1
    assert [record["sequence"] for record in records] == list(range(len(records)))
    assert len({record["record_id"] for record in records}) == len(records)


def test_concurrent_append_keeps_monotonic_unique_sequences(
    isolated_history: Path,
) -> None:
    # Given: one session receiving records from multiple worker threads.
    session_id = history.new_session("concurrent append")

    # When: all workers append at the same time.
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda number: history.append(
                    session_id, {"record": "user", "text": f"message-{number}"}
                ),
                range(32),
            )
        )

    # Then: every line remains readable and has one monotonic sequence identity.
    records = history.read(session_id)
    assert len(records) == 33
    assert [record["sequence"] for record in records] == list(range(33))
    assert len({record["record_id"] for record in records}) == 33


def test_list_sessions_reads_only_listing_metadata(
    isolated_history: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a valid transcript and a guard against whole-history reconstruction.
    session_id = history.new_session("fast listing")
    history.append(session_id, {"record": "user", "text": "hello"})
    monkeypatch.setattr(
        history,
        "read",
        lambda _session_id: pytest.fail("listing must not rehydrate transcripts"),
    )

    # When: the lightweight session index is requested.
    sessions = history.list_sessions()

    # Then: first-line metadata is returned without parsing the transcript body.
    assert [(item["session_id"], item["title"]) for item in sessions] == [(session_id, "fast listing")]
    assert set(sessions[0]) == {"session_id", "title", "updated_ms"}
    assert isinstance(sessions[0]["updated_ms"], int) and sessions[0]["updated_ms"] > 0


def test_list_sessions_reuses_and_updates_the_process_index(
    isolated_history: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: one listed transcript and an instrumented bounded metadata reader.
    first = history.new_session("first")
    original_listing_records = history_listing._listing_records
    listing_reads = 0

    def counted_listing_records(path: Path) -> tuple[dict[str, object], dict[str, object]]:
        nonlocal listing_reads
        listing_reads += 1
        return original_listing_records(path)

    monkeypatch.setattr(history_listing, "_listing_records", counted_listing_records)

    # When: the same process lists repeatedly, appends, creates, and detaches.
    assert [item["session_id"] for item in history.list_sessions()] == [first]
    assert [item["session_id"] for item in history.list_sessions()] == [first]
    history.append(first, {"record": "user", "text": "hello"})
    assert [item["session_id"] for item in history.list_sessions()] == [first]
    second = history.new_session("second")
    assert [item["session_id"] for item in history.list_sessions()] == [second, first]
    assert history.detach(second) is True
    assert [item["session_id"] for item in history.list_sessions()] == [first]

    # Then: only the initial transcript scan touched listing metadata.
    assert listing_reads == 1


def test_list_sessions_detects_an_external_archive_move(
    isolated_history: Path,
) -> None:
    session_id = history.new_session("external archive")
    assert [item["session_id"] for item in history.list_sessions()] == [session_id]

    source = history.chats_root() / f"{session_id}.jsonl"
    archive = isolated_history / "archive"
    archive.mkdir()
    source.replace(archive / source.name)

    assert history.list_sessions() == []


def test_list_sessions_orders_recently_modified_transcripts_first(
    isolated_history: Path,
) -> None:
    # Given: lexical session IDs whose modification order is deliberately reversed.
    root = history.chats_root()
    older = root / "aaaaaaaaaaaa.jsonl"
    newer = root / "bbbbbbbbbbbb.jsonl"
    older.write_text('{"record":"meta","title":"older"}\n', encoding="utf-8")
    newer.write_text('{"record":"meta","title":"newer"}\n', encoding="utf-8")
    os.utime(older, ns=(100, 100))
    os.utime(newer, ns=(200, 200))

    # When: the recent-chat listing is requested.
    sessions = history.list_sessions()

    # Then: recency, not the random session ID, determines display order.
    assert [session["session_id"] for session in sessions] == [newer.stem, older.stem]


@pytest.mark.parametrize("suffix", ["", "x", "xx"])
def test_list_sessions_handles_large_multibyte_tail_and_small_tombstone(
    isolated_history: Path, suffix: str
) -> None:
    # Given: a final JSONL record larger than the bounded listing tail window.
    session_id = history.new_session("multibyte tail")
    history.append(
        session_id, {"record": "assistant", "text": "한" * 5_000 + suffix}
    )

    # When: the live session is listed, then detached with a small final tombstone.
    live_ids = {item["session_id"] for item in history.list_sessions()}
    assert history.detach(session_id) is True
    detached_ids = {item["session_id"] for item in history.list_sessions()}

    # Then: mid-codepoint tail bytes never hide live history, while tombstones do.
    assert session_id in live_ids
    assert session_id not in detached_ids
