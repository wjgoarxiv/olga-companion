"""Settings status for the local CLI: found or not, a one-request Check, and the path override."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion.agent import session_token
from olga_companion.llm import claude_cli_discovery, claude_cli_launch, claude_cli_status, provider_runtime_status
from olga_companion.sidecar import app

FIXTURES = Path(__file__).parent / "fixtures" / "claude_cli"
FAKE = FIXTURES / "fake_claude.py"
HANGUL = re.compile(r"[가-힣]")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_cli_launch, "run_root", lambda: tmp_path / "runs")
    monkeypatch.setattr(claude_cli_launch, "harden_private_path", lambda _p, directory: None)
    monkeypatch.setattr(claude_cli_discovery, "override_path", lambda: tmp_path / "override.json")
    provider_runtime_status.reset_all()
    claude_cli_discovery.invalidate()
    yield
    claude_cli_discovery.invalidate()
    provider_runtime_status.reset_all()


def fake(tmp_path, monkeypatch, **scenario):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", str(path))
    found = claude_cli_discovery.CliResolution("ok", [sys.executable, str(FAKE)], str(FAKE), "2.1.220")
    monkeypatch.setattr(claude_cli_discovery, "resolve", lambda **_kw: found)


def _client():
    return TestClient(app, base_url="http://127.0.0.1:8865", client=("127.0.0.1", 50000))


def _headers():
    return {"X-Session-Token": session_token.boot_token()}


def test_every_diagnosis_has_korean_and_english_text():
    for code in claude_cli_status.DIAGNOSES:
        ko, en = claude_cli_status.diagnosis(code, "ko"), claude_cli_status.diagnosis(code, "en")
        assert HANGUL.search(ko) and en and not HANGUL.search(en), code


def test_status_reports_found_without_running_a_request(tmp_path, monkeypatch):
    capture = tmp_path / "capture.json"
    fake(tmp_path, monkeypatch, capture=str(capture))
    body = _client().get("/api/providers/claude_cli/status", headers=_headers()).json()
    assert body["code"] == "ok" and body["version"] == "2.1.220"
    assert "path" not in body
    assert HANGUL.search(body["message_ko"]) and body["message_en"]
    assert not capture.exists()


def test_status_needs_the_session_token():
    assert _client().get("/api/providers/claude_cli/status").status_code == 401


def test_status_when_not_installed(monkeypatch):
    monkeypatch.setattr(claude_cli_discovery, "resolve", lambda **_kw: claude_cli_discovery.CliResolution("not_installed"))
    body = _client().get("/api/providers/claude_cli/status", headers=_headers()).json()
    assert body["code"] == "not_installed"
    assert "claude" in body["message_en"].lower()


def test_check_runs_one_small_request_without_the_app_tools(tmp_path, monkeypatch):
    capture = tmp_path / "capture.json"
    fake(tmp_path, monkeypatch, replay=str(FIXTURES / "happy.jsonl"), capture=str(capture))
    body = _client().post("/api/providers/claude_cli/check", headers=_headers()).json()
    assert body["code"] == "ok"
    assert body["billing"] == "subscription"
    argv = json.loads(capture.read_text(encoding="utf-8"))["argv"]
    assert "--allowedTools" not in argv and "--strict-mcp-config" in argv
    assert not any((tmp_path / "runs").glob("run-*"))


def test_check_reports_not_signed_in(tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, replay=str(FIXTURES / "not_logged_in.jsonl"), exit=1)
    body = _client().post("/api/providers/claude_cli/check", headers=_headers()).json()
    assert body["code"] == "not_logged_in"
    assert "로그인" in body["message_ko"]
    assert provider_runtime_status.failed("claude_cli")


def test_check_needs_the_session_token():
    assert _client().post("/api/providers/claude_cli/check").status_code == 401


def test_path_override_is_saved_and_cleared(tmp_path):
    exe = tmp_path / "claude.exe"
    exe.write_bytes(b"")
    response = _client().put("/api/providers/claude_cli/path", json={"path": str(exe)}, headers=_headers())
    assert response.status_code == 200
    assert claude_cli_discovery.load_override() == str(exe.resolve())
    response = _client().put("/api/providers/claude_cli/path", json={"path": None}, headers=_headers())
    assert response.status_code == 200 and claude_cli_discovery.load_override() == ""


def test_a_bad_override_is_refused(tmp_path):
    response = _client().put("/api/providers/claude_cli/path", json={"path": str(tmp_path / "notepad.exe")},
                             headers=_headers())
    assert response.status_code == 400


def test_providers_list_puts_the_cli_last_and_marks_it_local():
    providers = _client().get("/api/providers", headers=_headers()).json()["providers"]
    assert [p["provider"] for p in providers][-1] == "claude_cli"
    assert [p["provider"] for p in providers][:5] == ["openai", "copilot", "antigravity", "xai", "apikey"]
    assert providers[-1]["login"] == "local_cli"
    assert [m["id"] for m in providers[-1]["models"]] == ["default", "sonnet", "opus", "haiku"]


def test_is_connected_never_waits_on_the_cli(monkeypatch):
    monkeypatch.setattr(claude_cli_discovery, "peek", claude_cli_discovery.peek_now)
    import time

    from olga_companion.llm import catalog

    def slow(**_kw):
        time.sleep(5)
        return claude_cli_discovery.CliResolution("ok", ["x"], "x", "2.1.220")

    monkeypatch.setattr(claude_cli_discovery, "resolve", slow)
    t0 = time.time()
    assert catalog.is_connected("claude_cli") is False
    assert time.time() - t0 < 1


def test_is_connected_after_a_sign_in_failure_is_false(monkeypatch):
    monkeypatch.setattr(claude_cli_discovery, "peek", claude_cli_discovery.peek_now)
    from olga_companion.llm import catalog

    found = claude_cli_discovery.CliResolution("ok", ["x"], "x", "2.1.220")
    claude_cli_discovery._cache[claude_cli_discovery.load_override()] = (__import__("time").monotonic(), found)
    assert catalog.is_connected("claude_cli") is True
    provider_runtime_status.record_auth_failure("claude_cli")
    assert catalog.is_connected("claude_cli") is False


def test_check_finds_the_cli_off_the_event_loop(tmp_path, monkeypatch):
    import threading

    fake(tmp_path, monkeypatch, replay=str(FIXTURES / "happy.jsonl"))
    found = claude_cli_discovery.resolve()
    threads = []

    def resolve(**_kw):
        threads.append(threading.current_thread() is threading.main_thread())
        return found

    monkeypatch.setattr(claude_cli_discovery, "resolve", resolve)
    assert asyncio.run(claude_cli_status.check())["code"] == "ok"
    assert threads == [False]


def test_check_refuses_a_cmd_shim_when_its_arguments_are_unsafe(tmp_path, monkeypatch):
    from olga_companion.llm import claude_cli_process

    monkeypatch.setattr(claude_cli_launch, "run_root", lambda: tmp_path / "A&B")
    shim = claude_cli_discovery.CliResolution("ok", ["cmd.exe", "/d", "/s", "/c", r"C:\npm\claude.cmd"],
                                               r"C:\npm\claude.cmd", "2.1.330")
    monkeypatch.setattr(claude_cli_discovery, "resolve", lambda **_kw: shim)

    def never(*_a, **_kw):
        raise AssertionError("nothing may be started")

    monkeypatch.setattr(claude_cli_process.CliProcess, "start", never)
    body = asyncio.run(claude_cli_status.check())
    assert body["code"] == "cmd_shim_unsafe"
    assert body["message_ko"] and body["message_en"]


def test_find_again_skips_the_cached_answer(monkeypatch):
    answers = iter([claude_cli_discovery.CliResolution("not_installed"),
                    claude_cli_discovery.CliResolution("ok", ["x"], "x", "2.1.330")])
    calls = []

    def resolve(**kw):
        calls.append(kw.get("use_cache", True))
        return next(answers)

    monkeypatch.setattr(claude_cli_discovery, "resolve", resolve)
    assert _client().get("/api/providers/claude_cli/status", headers=_headers()).json()["code"] == "not_installed"
    body = _client().get("/api/providers/claude_cli/status?fresh=1", headers=_headers()).json()
    assert body["code"] == "ok" and len(calls) == 2


def test_the_not_installed_advice_is_something_the_panel_can_do():
    for code in ("not_installed", "override_missing"):
        for locale in ("ko", "en"):
            text = claude_cli_status.diagnosis(code, locale)
            assert "직접 지정" not in text and "choose" not in text.lower() and "지정을 지우" not in text, (code, locale)


def test_find_again_also_updates_what_the_provider_list_sees(monkeypatch):
    claude_cli_discovery.invalidate()
    answers = iter([claude_cli_discovery.CliResolution("not_installed"),
                    claude_cli_discovery.CliResolution("ok", ["x"], "x", "2.1.330")])
    monkeypatch.setattr(claude_cli_discovery, "_resolve", lambda *a: next(answers))
    monkeypatch.setattr(claude_cli_discovery, "load_override", lambda: "")
    assert claude_cli_status.status()["code"] == "not_installed"
    assert claude_cli_status.status(fresh=True)["code"] == "ok"
    assert claude_cli_discovery.peek_now().code == "ok"
