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


@pytest.mark.parametrize("name", ["fixture.ppl", "fixture.tpl", "controller_loop.tpl"])
def test_a_load_starts_the_parser_once(name: str, monkeypatch: pytest.MonkeyPatch):
    # The installed app pays about 3 s to start each parser, so three starts made a load take 10 s.
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(FIX))
    results._LOAD_CACHE.clear()
    real, calls = results.run_tool, []
    monkeypatch.setattr(results, "run_tool", lambda *a, **k: (calls.append(a), real(*a, **k))[1])
    loaded = results.load_result(str(FIX / name))
    assert loaded["ok"] is True and loaded["variables"]
    assert len(calls) == 1
    if name.endswith(".ppl"):
        assert loaded["branches"] and loaded["timesteps"]
    else:
        assert loaded["time_range"]["samples"] > 1


def test_one_load_answers_what_the_single_questions_answer(monkeypatch: pytest.MonkeyPatch):
    import json

    for name in ("fixture.ppl", "eval_case.ppl", "fixture.tpl"):
        path = str(FIX / name)

        def ask(*flags: str):
            return json.loads(results.run_tool("result_parser", [path, *flags, "--json"], names=results.RESULT_SCRIPTS).stdout)

        index = ask("--index")
        assert index["variables"] == ask("--list-vars")
        if name.endswith(".ppl"):
            assert sorted(index["branches"]) == sorted(ask("--list-branches"))
            assert index["timesteps"] == ask("--list-timesteps")
        else:
            time = ask("-v", index["variables"][0]["variable"])["time"]
            assert index["time_range"] == {"start_s": time[0], "end_s": time[-1], "samples": len(time)}


def test_a_trend_file_with_no_readable_series_still_lists_its_variables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    text = (FIX / "fixture.tpl").read_text(encoding="utf-8")
    (tmp_path / "cut.tpl").write_text(text[: text.index("\n", text.index("TIME SERIES")) + 1], encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    results._LOAD_CACHE.clear()
    loaded = results.load_result(str(tmp_path / "cut.tpl"))
    assert loaded["ok"] is True and loaded["variables"] and "time_range" not in loaded
