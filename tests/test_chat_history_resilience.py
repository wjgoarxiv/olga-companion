"""Failing-first resilience contracts for canonical Chat JSONL."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from olga_companion.agent import history
from olga_companion.agent.history_policy import MAX_STRING_CHARS


@pytest.fixture
def isolated_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    yield tmp_path


def test_oversized_record_retains_canonical_identity_envelope(
    isolated_history: Path,
) -> None:
    # Given: essential replay identity surrounding evidence above the record cap.
    session_id = history.new_session("oversized")
    envelope = {
        "record": "event",
        "type": "tool_result",
        "turn_id": "turn-1",
        "request_id": "request-1",
        "call_id": "call-1",
        "name": "results_load",
        "provider": "provider-a",
        "model": "model-a",
        "workspace_generation": 4,
        "workspace_root": "path-sha256:root-id",
        "state": "completed",
        "result": {
            f"column-{index}": "x" * (MAX_STRING_CHARS + 1)
            for index in range(9)
        },
    }

    # When: the oversized record is persisted.
    history.append(session_id, envelope)
    record = history.read(session_id)[1]

    # Then: payload is truncated but every routing/replay identity remains intact.
    for key in (
        "record", "type", "turn_id", "request_id", "call_id", "name",
        "provider", "model", "workspace_generation", "workspace_root", "state",
    ):
        assert record[key] == envelope[key]
    assert record["truncated"] is True
    assert record["payload_hash"].startswith("sha256:")
    assert "result" not in record


@pytest.mark.parametrize(
    "credential_key",
    [
        "client_secret", "private_key", "x-api-key", "apiKey", "serviceToken",
        "aws_access_key_id", "aws_secret_access_key", "credentials", "accessKey",
    ],
)
def test_nested_credential_key_variants_are_removed(
    isolated_history: Path, credential_key: str
) -> None:
    # Given: a nested provider-specific spelling of credential material.
    session_id = history.new_session("credentials")

    # When: an otherwise replayable result crosses the persistence boundary.
    history.append(
        session_id,
        {
            "record": "event",
            "type": "tool_result",
            "result": {credential_key: "do-not-persist", "source": "case.ppl"},
        },
    )

    # Then: nested credential variants are dropped while relative evidence remains.
    result = history.read(session_id)[1]["result"]
    assert result == {"source": "case.ppl"}


def test_benign_identity_keys_are_not_credentials(isolated_history: Path) -> None:
    session_id = history.new_session("benign ids")
    identity = {"artifact_id": "artifact-1", "call_id": "call-1", "selection_id": "case-1"}
    history.append(session_id, {"record": "event", "result": identity})
    assert history.read(session_id)[1]["result"] == identity


@pytest.mark.parametrize(
    "credential_key",
    ["aws_access_key_id", "aws_secret_access_key", "credentials", "accessKey"],
)
def test_raw_arguments_remove_cloud_credential_variants(
    isolated_history: Path, credential_key: str
) -> None:
    session_id = history.new_session("raw cloud credential")
    history.append(
        session_id,
        {
            "record": "event", "type": "tool_call",
            "raw_arguments": json.dumps(
                {credential_key: "do-not-persist", "path": "case.ppl"}
            ),
        },
    )
    record = history.read(session_id)[1]
    assert json.loads(record["raw_arguments"]) == {"path": "case.ppl"}
    assert "do-not-persist" not in (
        history.chats_root() / f"{session_id}.jsonl"
    ).read_text(encoding="utf-8")


def test_top_level_credential_variant_is_refused(
    isolated_history: Path,
) -> None:
    # Given: a credential-shaped field at the canonical record envelope boundary.
    session_id = history.new_session("top-level credential")

    # When / Then: the record is refused instead of silently losing its identity.
    with pytest.raises(ValueError, match="credential"):
        history.append(
            session_id,
            {"record": "user", "text": "hello", "clientSecret": "secret"},
        )


def test_private_credential_paths_are_hashed_but_relative_cases_survive(
    isolated_history: Path,
) -> None:
    # Given: ordinary relative case paths plus private credential-bearing paths.
    session_id = history.new_session("paths")
    absolute_paths = {
        "private_project": "/mnt/c/Users/Woojin/Desktop/PrivateProject/case.genkey",
        "netrc": "/home/operator/.netrc",
        "windows": r"C:\Users\Woojin\PrivateProject\case.genkey",
        "unc": r"\\server\private\case.genkey",
    }

    # When: nested arguments are persisted.
    history.append(
        session_id,
        {
            "record": "event",
            "type": "tool_call",
            "raw_arguments": json.dumps(
                {
                    "path": "cases/demo.genkey", **absolute_paths,
                    "callback": "prefix=https://user:password@example.invalid/result",
                }
            ),
            "args": {
                "path": "cases/demo.genkey",
                "existing_identity": "path-sha256:already-opaque",
                **absolute_paths,
                "callback": "prefix=https://user:password@example.invalid/result",
            },
        },
    )

    # Then: replay-safe relative paths remain and private locations become opaque.
    args = history.read(session_id)[1]["args"]
    assert args["path"] == "cases/demo.genkey"
    assert args["existing_identity"] == "path-sha256:already-opaque"
    assert all(args[key].startswith("path-sha256:") for key in absolute_paths)
    assert args["callback"].startswith("url-sha256:")
    assert not any(path in json.dumps(args) for path in absolute_paths.values())
    raw_args = json.loads(history.read(session_id)[1]["raw_arguments"])
    assert raw_args["path"] == "cases/demo.genkey"
    assert all(raw_args[key].startswith("path-sha256:") for key in absolute_paths)
    assert raw_args["callback"].startswith("url-sha256:")


@pytest.mark.parametrize("partial_mode", ["half", "without-newline"])
def test_partial_final_write_is_rolled_back_then_repaired(
    isolated_history: Path,
    monkeypatch: pytest.MonkeyPatch,
    partial_mode: str,
) -> None:
    # Given: an interrupted append ending in a fragment or valid JSON without newline.
    session_id = history.new_session("partial")
    original_write = history.os.write

    def partial_write(descriptor: int, payload: bytes) -> int:
        size = len(payload) // 2 if partial_mode == "half" else len(payload) - 1
        return original_write(descriptor, payload[:size])

    monkeypatch.setattr(history.os, "write", partial_write)
    with pytest.raises(OSError, match="incomplete"):
        history.append(session_id, {"record": "user", "text": "interrupted"})
    monkeypatch.setattr(history.os, "write", original_write)

    # When: history is read and another complete append follows.
    assert [record["record"] for record in history.read(session_id)] == ["meta"]
    history.append(session_id, {"record": "user", "text": "recovered"})

    # Then: the fragment is removed and the repaired file is canonical JSONL.
    records = history.read(session_id)
    assert [record["sequence"] for record in records] == [0, 1]
    assert records[1]["text"] == "recovered"
    path = history.chats_root() / f"{session_id}.jsonl"
    assert all(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())


def test_append_repairs_valid_legacy_final_line_without_newline(
    isolated_history: Path,
) -> None:
    # Given: a valid legacy final JSON object whose terminating newline was lost.
    session_id = history.new_session("legacy no newline")
    history.append(session_id, {"record": "user", "text": "first"})
    path = history.chats_root() / f"{session_id}.jsonl"
    path.write_bytes(path.read_bytes().removesuffix(b"\n"))

    # When: another canonical record is appended.
    history.append(session_id, {"record": "assistant", "text": "second"})

    # Then: append repairs the delimiter rather than concatenating JSON objects.
    assert [record["text"] for record in history.read(session_id)[1:]] == [
        "first",
        "second",
    ]
    assert path.read_bytes().endswith(b"\n")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_malformed_middle_line_fails_closed(isolated_history: Path) -> None:
    # Given: corruption between two otherwise complete canonical records.
    session_id = history.new_session("middle corruption")
    history.append(session_id, {"record": "user", "text": "valid"})
    path = history.chats_root() / f"{session_id}.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], "{malformed", lines[1]]) + "\n", encoding="utf-8")

    # When / Then: a middle-line corruption is never silently discarded.
    with pytest.raises(ValueError, match="middle"):
        history.read(session_id)
