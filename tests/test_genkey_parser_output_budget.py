"""The flowpath preview must survive a real production case.

A 420 KB `.genkey` from a real study expands to 2.47 MiB of pretty-printed JSON,
which overran `FLOWPATH_TOOL_OUTPUT_BYTES` (2 MiB) and made every flowpath click
fail with "Flowpath geometry exceeds the supported output limit." The topology
graph on the same screen kept working because it reads the same parser output
under the 8 MiB default budget.

Nothing consumes the CLI's JSON by eye -- the app calls `json.loads` on it -- so
the indentation was more than half the payload for no benefit.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from olga_companion import config, genkey_static
from olga_companion.genkey_tool_runner import DEFAULT_TOOL_OUTPUT_BYTES

PARSER = config.toolkit_dir() / "scripts" / "genkey_parser.py"
FIXTURE = Path(__file__).parent / "fixtures" / "fluids" / "case_ok.genkey"

pytestmark = pytest.mark.skipif(
    not PARSER.exists() or not FIXTURE.exists(),
    reason="toolkit parser or genkey fixture unavailable",
)


def _invoke(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PARSER), str(FIXTURE), *args],
        capture_output=True,
        text=True,
        timeout=120,
        # The toolkit directory ships inside the installer verbatim, and .pyc
        # embeds the build machine's absolute source path. genkey_tool_runner
        # sets this for the same reason; a test that spawns the script directly
        # has to as well, or it quietly reintroduces the leak.
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _run(args: list[str]) -> str:
    completed = _invoke(args)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_flowpath_budget_is_not_stricter_than_every_other_toolkit_call() -> None:
    # The flowpath view reads the whole case document, exactly like the topology
    # graph does. Giving it a smaller budget than the default meant the graph
    # rendered and the flowpath detail beside it failed on the same file.
    assert genkey_static.FLOWPATH_TOOL_OUTPUT_BYTES >= DEFAULT_TOOL_OUTPUT_BYTES


def test_parser_cli_emits_compact_json_on_request() -> None:
    compact = _run(["--compact"])

    assert json.loads(compact), "compact output must still be valid JSON"
    # Pretty-printing puts a newline after every element; compact must not.
    assert compact.count("\n") <= 1, "compact output must not be indented"
    assert ",\n" not in compact and ": " not in compact


def test_compact_output_is_materially_smaller_than_pretty() -> None:
    pretty = _run([])
    compact = _run(["--compact"])

    assert len(compact) < len(pretty)
    # On the real 420 KB case this ratio is what moves 2.47 MiB under budget.
    assert len(compact) <= len(pretty) * 0.75


def test_pretty_remains_the_default_for_human_invocation() -> None:
    # Other toolkit scripts and operators run this CLI directly; changing the
    # bare-invocation default would be a surprise for them.
    assert "\n" in _run([])


def test_compact_and_pretty_describe_the_same_case() -> None:
    assert json.loads(_run(["--compact"])) == json.loads(_run([]))


def test_unknown_flags_are_rejected_rather_than_silently_ignored() -> None:
    # `--json` was passed by the app for months and quietly did nothing, which
    # is how the payload stayed pretty-printed without anyone noticing.
    completed = _invoke(["--not-a-real-flag"])
    assert completed.returncode != 0
    assert "--not-a-real-flag" in completed.stderr
