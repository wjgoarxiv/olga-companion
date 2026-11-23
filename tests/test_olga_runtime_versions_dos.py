"""Version and input-file patterns stay linear on blank-line floods (security review C2).

``(?im)^\\s*`` let ``\\s`` run across newlines from every line start, so a run
output of a few hundred KiB of blank lines froze the sidecar.
"""

from __future__ import annotations

import time

import pytest

from olga_companion import olga_runtime_versions as versions

PATTERNS = [
    versions.OUT_VERSION,
    versions.OUT_INPUT,
    versions.NORMAL_STOP,
    versions.RESULT_VERSION,
    versions.RESULT_INPUT,
    versions.RESULT_INPUT_MULTILINE,
]

FLOODS = {
    "newlines": "\n" * (1 << 20),
    "crlf": "\r\n" * (1 << 19),
    "spaced": " \n" * (1 << 19),
}


@pytest.mark.parametrize("flood", FLOODS.values(), ids=FLOODS.keys())
def test_each_pattern_is_fast_on_a_one_mebibyte_flood(flood: str) -> None:
    for pattern in PATTERNS:
        started = time.perf_counter()
        pattern.search(flood)
        assert time.perf_counter() - started < 1.0, pattern.pattern


@pytest.mark.parametrize("blank", [" ", "\t"], ids=["spaces", "tabs"])
def test_each_pattern_is_fast_on_one_long_line_of_blanks(blank: str) -> None:
    # The value capture and the trailing blanks must not both be able to take the same characters.
    for prefix in ("INPUT FILE : a", " 'INPUT FILE' 'a", " VERSION : OLGA 2025.1.0", ""):
        line = prefix + blank * 200_000 + "'x\n"
        for pattern in PATTERNS:
            started = time.perf_counter()
            pattern.search(line)
            assert time.perf_counter() - started < 1.0, (prefix, pattern.pattern)


def test_the_multiline_input_file_still_crosses_blank_lines() -> None:
    match = versions.RESULT_INPUT_MULTILINE.search(" 'INPUT FILE'\n\n   \r\n  'c.genkey'\n")
    assert match is not None and match.group(2) == "c.genkey"


def test_patterns_still_read_real_lines() -> None:
    assert versions.OUT_VERSION.search("x\n   VERSION : OLGA 2025.1.0\n").groups() == ("2025", "1", "0")
    assert versions.OUT_INPUT.search("  INPUT FILE : 'case.genkey'  \n").group(1) == "case.genkey"
    assert versions.RESULT_VERSION.search("\n 'OLGA 2024.2.1'\n").group(2) == "2024"
    assert versions.RESULT_INPUT.search(" 'INPUT FILE' 'a.genkey'\n").group(3) == "a.genkey"
    multiline = versions.RESULT_INPUT_MULTILINE.search(" 'INPUT FILE'\r\n  'b.genkey'\n")
    assert multiline is not None and multiline.group(2) == "b.genkey"
