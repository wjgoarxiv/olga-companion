"""WS0 — pyfas .ppl load robustness: adequate timeout + sha256-cached index.

A real 1.4 MB .ppl needs ~81s to list branches, but load_result ran the parser
under run_tool's default 30s, so the first real file a user loaded returned
ok=False while the capability reported "enabled" (only an 892-byte fixture tested).
"""
from pathlib import Path

import pytest

from olga_companion import results

FIX = Path(__file__).parent / "fixtures" / "results"


def test_result_load_timeout_is_adequate_for_a_real_ppl():
    # The list-branches/list-timesteps calls must not run under the 30s default.
    assert results.RESULT_LOAD_TIMEOUT_S >= 180


def test_load_result_caches_the_index_by_sha256(monkeypatch: pytest.MonkeyPatch):
    ppl = FIX / "fixture.ppl"
    if not ppl.exists():
        pytest.skip("fixture.ppl missing")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(FIX))
    results._LOAD_CACHE.clear()
    first = results.load_result(str(ppl))
    assert first["ok"] is True
    assert first["cached"] is False
    second = results.load_result(str(ppl))
    assert second["cached"] is True  # repeat load served from the sha256 index, no re-parse
    assert second["variables"] == first["variables"]
    assert second["branches"] == first["branches"]
