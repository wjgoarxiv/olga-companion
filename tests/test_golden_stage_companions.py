"""R8: staging a run keeps the case bytes and rewrites only the exact file reference."""

from __future__ import annotations

from pathlib import Path

from olga_companion.run_companions import (
    effective_companion_manifest,
    expected_staged_source_sha256,
    stage_companions,
)

COMMENT = "! 한국어 메모 ../shared/a.tab.bak and data_a.tab\n".encode("cp949")


def _case(tmp_path: Path) -> tuple[Path, Path, Path]:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "a.tab").write_text("table", encoding="utf-8")
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    source = case_dir / "case.genkey"
    source.write_bytes(COMMENT + b'FILES PVTFILE="../shared/a.tab"\nENDCASE\n')
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    working = run_dir / "case.genkey"
    working.write_bytes(source.read_bytes())
    return source, working, run_dir


def test_r8_non_utf8_comment_bytes_survive_staging(tmp_path: Path) -> None:
    source, working, run_dir = _case(tmp_path)
    evidence = stage_companions(source, working, run_dir)
    staged = working.read_bytes()
    assert evidence["pvt_files"] == ["../shared/a.tab"]
    assert staged.startswith(COMMENT)
    assert b'PVTFILE="./a.tab"' in staged
    assert (run_dir / "a.tab").read_text(encoding="utf-8") == "table"


def test_r8_staged_hash_matches_the_expectation(tmp_path: Path) -> None:
    import hashlib

    source, working, run_dir = _case(tmp_path)
    manifest = effective_companion_manifest(source)
    expected = expected_staged_source_sha256(source, manifest, run_dir)
    stage_companions(source, working, run_dir)
    assert hashlib.sha256(working.read_bytes()).hexdigest() == expected


def test_r8_only_the_reference_value_is_rewritten() -> None:
    from olga_companion.run_companions import _rewrite_reference

    text = (
        'FILES PVTFILE="../shared/a.tab"\n'
        "! ../shared/a.tab was the old table\n"
        "DRILLFILE=../shared/a.tab\n"
        "RESTART FILE=../shared/a.tab, READFILE=ON ! keep ../shared/a.tab\n"
    )
    assert _rewrite_reference(text, "../shared/a.tab", "./a.tab") == (
        'FILES PVTFILE="./a.tab"\n'
        "! ../shared/a.tab was the old table\n"
        "DRILLFILE=../shared/a.tab\n"
        "RESTART FILE=./a.tab, READFILE=ON ! keep ../shared/a.tab\n"
    )


def test_r8_a_name_differing_only_by_case_is_left_alone() -> None:
    from olga_companion.run_companions import _rewrite_reference

    text = "PVTFILE = a.tab\nPVTFILE = A.TAB\npvtfile = a.tab\n"
    assert _rewrite_reference(text, "a.tab", "./x.tab") == "PVTFILE = ./x.tab\nPVTFILE = A.TAB\npvtfile = ./x.tab\n"
