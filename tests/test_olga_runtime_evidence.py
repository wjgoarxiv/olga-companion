from __future__ import annotations

import os
import time
from pathlib import Path

from olga_companion.olga_runtime import (
    MAX_EVIDENCE_BYTES,
    _read_bounded,
    detect_olga as detect_runtime,
)
from olga_runtime_test_support import _installed_release, _qualified_case


def test_stale_output_is_visible_but_does_not_constrain_selection(
    tmp_path: Path,
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2022.1.0", engine=False)
    _installed_release(installs, "2025.1.0", engine=False)
    case = _qualified_case(tmp_path / "package", "2022.1.0")
    output = case.parent / "results" / "case.out"
    case_mtime = output.stat().st_mtime_ns + 1_000_000_000
    os.utime(case, ns=(case_mtime, case_mtime))

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")],
        environ={},
        source=case,
    )

    assert detection["detected"] is True
    assert detection["selection_status"] == "selected_fallback"
    assert detection["version"] == "2025.1.0"
    assert detection["required_version"] is None
    assert detection["evidence"][0]["strength"] == "stale"


def test_unqualified_or_unrelated_version_text_is_not_case_evidence(
    tmp_path: Path,
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.1.0", engine=False)
    case_dir = tmp_path / "package"
    case_dir.mkdir()
    case = case_dir / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n")
    (case_dir / "case.out").write_text(
        "VERSION : OLGA 2022.1.0.35696\nINPUT FILE : case.genkey\n"
    )
    (case_dir / "case.bat").write_text(
        "VERSION : OLGA 2022.1.0.35696\nINPUT FILE : case.genkey\nNORMAL STOP IN EXECUTION\n"
    )
    (case_dir / "fluid.tab").write_text("Multiflash version 2022.1.0\n")

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")],
        environ={},
        source=case,
    )

    assert detection["version"] == "2025.1.0"
    assert detection["selection_status"] == "selected_fallback"
    assert detection["evidence"] == []


def test_large_solver_out_uses_bounded_head_and_tail_evidence(tmp_path: Path) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2022.1.0", engine=False)
    case_dir = tmp_path / "package"
    case_dir.mkdir()
    case = case_dir / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n")
    (case_dir / "case.out").write_text(
        "VERSION : OLGA 2022.1.0.35696\nINPUT FILE : case.genkey\n"
        + ("solver detail\n" * 30000)
        + "**************** NORMAL STOP IN EXECUTION ****************\n"
    )

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")],
        environ={},
        source=case,
    )

    assert detection["required_version"] == "2022.1.0"
    assert detection["evidence"][0]["bytes_read"] <= 256 * 1024


def test_bounded_evidence_does_not_promote_a_tail_fragment_to_a_version_line(
    tmp_path: Path,
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.1.0", engine=False)
    case_dir = tmp_path / "package"
    case_dir.mkdir()
    case = case_dir / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n")
    half = MAX_EVIDENCE_BYTES // 2
    qualified_tail = (
        b"VERSION : OLGA 2022.1.0.35696\n"
        b"INPUT FILE : case.genkey\n"
        b"**************** NORMAL STOP IN EXECUTION ****************\n"
    )
    # In the full file VERSION is part of one X-prefixed line and is invalid.
    # The old bounded reader inserted a newline exactly before qualified_tail,
    # manufacturing a strong version record that the full file never had.
    tail = qualified_tail + (b"tail filler" * ((half - len(qualified_tail)) // 11 + 1))
    tail = tail[:half]
    (case_dir / "case.out").write_bytes((b"X" * (half + 1)) + tail)

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")],
        environ={},
        source=case,
    )

    assert detection["required_version"] is None
    assert detection["version"] == "2025.1.0"
    assert detection["evidence"] == []


def test_bounded_reader_preserves_complete_crlf_head_and_tail_records(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "case.out"
    evidence.write_bytes(
        b"VERSION : OLGA 2022.1.0.35696\r\n"
        b"INPUT FILE : case.genkey\r\n"
        + (b"solver detail\r\n" * 30000)
        + b"**************** NORMAL STOP IN EXECUTION ****************\r\n"
    )

    text, bytes_read = _read_bounded(evidence)

    assert "VERSION : OLGA 2022.1.0.35696\r\n" in text
    assert "INPUT FILE : case.genkey\r\n" in text
    assert "NORMAL STOP IN EXECUTION" in text
    assert bytes_read <= MAX_EVIDENCE_BYTES


def test_bounded_reader_discards_both_malformed_boundary_fragments(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "case.out"
    half = MAX_EVIDENCE_BYTES // 2
    head_prefix = b"HEAD COMPLETE\r\n"
    head_fragment = b"MALFORMED_HEAD"
    head = (
        head_prefix
        + (b"h" * (half - len(head_prefix) - len(head_fragment)))
        + head_fragment
    )
    tail_fragment = b"MALFORMED_TAIL\r\n"
    tail_record = b"TAIL COMPLETE\r\n"
    tail = (
        tail_fragment
        + tail_record
        + (b"t" * (half - len(tail_fragment) - len(tail_record)))
    )
    evidence.write_bytes(head + tail + b"t")

    text, bytes_read = _read_bounded(evidence)

    assert "HEAD COMPLETE\r\n" in text
    assert "TAIL COMPLETE\r\n" in text
    assert "MALFORMED_HEAD" not in text
    assert "MALFORMED_TAIL" not in text
    assert bytes_read <= MAX_EVIDENCE_BYTES


def test_bounded_reader_returns_no_fragment_from_a_giant_line_without_newline(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "case.out"
    evidence.write_bytes(b"x" * (MAX_EVIDENCE_BYTES * 2))

    text, bytes_read = _read_bounded(evidence)

    assert text == ""
    assert bytes_read <= MAX_EVIDENCE_BYTES


def test_future_dated_case_evidence_is_not_strong(tmp_path: Path) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.1.0", engine=False)
    case = _qualified_case(tmp_path / "package", "2022.1.0")
    output = case.parent / "results" / "case.out"
    future = time.time_ns() + 60_000_000_000
    os.utime(output, ns=(future, future))

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")],
        environ={},
        source=case,
    )

    assert detection["required_version"] is None
    assert detection["version"] == "2025.1.0"
    assert detection["evidence"] == []
