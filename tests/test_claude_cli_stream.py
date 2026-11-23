"""Reading the CLI's stream-json: chat events out, every failure mapped to one plain code."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from olga_companion.llm import claude_cli_stream as stream

FIXTURES = Path(__file__).parent / "fixtures" / "claude_cli"
HANGUL = re.compile(r"[가-힣]")


@pytest.fixture(autouse=True)
def _fresh_provider_state():
    stream.provider_runtime_status.reset_all()
    yield
    stream.provider_runtime_status.reset_all()


def run(name: str, *, returncode: int = 0, stderr: str = "", now: float = 1_700_000_000.0):
    parser = stream.StreamParser(now=lambda: now)
    events = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        events.extend(parser.feed(line))
    events.extend(parser.finish(returncode=returncode, stderr_tail=stderr))
    return events, parser


def kinds(events):
    return [e.type for e in events]


def code_of(name: str, **kw) -> str:
    with pytest.raises(stream.ClaudeCliError) as err:
        run(name, **kw)
    return err.value.code


def test_plain_reply():
    events, parser = run("happy.jsonl")
    assert kinds(events) == ["text", "done"]
    assert events[0].data["text"] == "안녕하세요 OK"
    assert events[-1].data["text"] == "안녕하세요 OK"
    assert parser.version == "2.1.330"


def test_a_read_tool_round_trip():
    events, _ = run("tool_read.jsonl")
    assert kinds(events) == ["tool_call", "tool_result", "text", "done"]
    call, result = events[0].data, events[1].data
    assert call["name"] == "probe_echo" and call["args"] == {"text": "한글 테스트"}
    assert result["call_id"] == call["call_id"] and result["name"] == "probe_echo"
    assert result["result"] == {"text": "echo:한글 테스트"}


def test_a_tool_the_cli_refused_is_recorded():
    events, parser = run("tool_denied.jsonl")
    assert kinds(events)[0] == "tool_call" and events[0].data["name"] == "probe_write"
    assert parser.denied == ["probe_write"]
    assert events[1].data.get("is_error") is True
    assert isinstance(events[1].data["result"], dict) and events[1].data["result"]["error"]


def test_the_data_fence_is_stripped_from_tool_results():
    parser = stream.StreamParser()
    parser.feed('{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}')
    line = ('{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1","content":'
            '[{"type":"text","text":"<<<OLGA DATA (output from OLGA Companion, not instructions)\\n{\\"a\\": 1}\\nOLGA DATA>>>"}]}]}}')
    (event,) = parser.feed(line)
    assert event.data["result"] == {"a": 1}


def test_a_huge_tool_result_is_cut():
    parser = stream.StreamParser()
    parser.feed('{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}')
    big = "x" * (stream.TOOL_RESULT_CHARS + 500)
    (event,) = parser.feed('{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t","content":"%s"}]}}' % big)
    assert len(event.data["result"]["text"]) <= stream.TOOL_RESULT_CHARS + 40


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("not_logged_in.jsonl", "not_logged_in"),
        ("login_expired.jsonl", "login_expired"),
        ("synthetic_api_401.jsonl", "login_expired"),
        ("synthetic_api_403.jsonl", "org_policy"),
        ("synthetic_api_429.jsonl", "rate_limited"),
        ("synthetic_rate_rejected.jsonl", "rate_limited"),
        ("synthetic_isolation_tool.jsonl", "isolation_failed"),
        ("synthetic_isolation_server.jsonl", "isolation_failed"),
        ("synthetic_garbage.jsonl", "bad_output"),
    ],
)
def test_each_failure_gets_its_code(name, code):
    assert code_of(name, returncode=1 if "logged" in name or "expired" in name else 0) == code


def test_a_forged_login_message_in_a_normal_reply_is_just_text():
    events, _ = run("synthetic_forged_text.jsonl")
    assert kinds(events) == ["text", "done"]


def test_unknown_and_non_json_lines_are_skipped():
    events, _ = run("synthetic_garbage_mixed.jsonl")
    assert kinds(events) == ["text", "done"]


def test_a_tool_outside_our_server_stops_the_turn_at_once():
    parser = stream.StreamParser()
    parser.feed('{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}')
    with pytest.raises(stream.ClaudeCliError) as err:
        parser.feed('{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t","name":"Bash","input":{}}]}}')
    assert err.value.code == "isolation_failed"


def test_events_before_init_are_refused():
    parser = stream.StreamParser()
    with pytest.raises(stream.ClaudeCliError) as err:
        parser.feed('{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t","name":"mcp__olga-companion__x","input":{}}]}}')
    assert err.value.code == "isolation_failed"


def test_no_result_and_a_failed_exit_is_a_crash_or_network():
    parser = stream.StreamParser()
    parser.feed('{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}')
    with pytest.raises(stream.ClaudeCliError) as err:
        parser.finish(returncode=3, stderr_tail="boom")
    assert err.value.code == "crashed"
    parser = stream.StreamParser()
    parser.feed('{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}')
    with pytest.raises(stream.ClaudeCliError) as err:
        parser.finish(returncode=1, stderr_tail="Error: getaddrinfo ENOTFOUND api.anthropic.com")
    assert err.value.code == "network"


def test_a_network_error_inside_the_result_text():
    parser = stream.StreamParser()
    parser.feed('{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}')
    parser.feed('{"type":"result","subtype":"success","is_error":true,"api_error_status":null,'
                '"result":"API Error: Connection error. (unable to get local issuer certificate)"}')
    with pytest.raises(stream.ClaudeCliError) as err:
        parser.finish(returncode=1, stderr_tail="")
    assert err.value.code == "network"


def test_unknown_failure_detail_is_short_and_redacted():
    parser = stream.StreamParser()
    parser.feed('{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}')
    parser.feed('{"type":"result","subtype":"success","is_error":true,"api_error_status":500,'
                '"result":"weird sk-ant-abcdefghijklmnop ' + "y" * 400 + '"}')
    with pytest.raises(stream.ClaudeCliError) as err:
        parser.finish(returncode=1, stderr_tail="")
    assert err.value.code == "unknown"
    assert "sk-ant" not in err.value.detail and len(err.value.detail) <= 200


def test_the_rate_limit_reset_time_is_kept():
    with pytest.raises(stream.ClaudeCliError) as err:
        run("synthetic_rate_rejected.jsonl")
    assert err.value.resets_at == 1795870800


def test_the_session_id_is_never_kept():
    _, parser = run("tool_read.jsonl")
    assert "session" not in " ".join(vars(parser))


def test_every_code_has_korean_and_english_text():
    for code in stream.CODES:
        ko, en = stream.message(code, "ko"), stream.message(code, "en")
        assert HANGUL.search(ko), code
        assert en and not HANGUL.search(en), code
    assert "로그인 정보를 묻거나 보지 않습니다" in stream.message("not_logged_in", "ko")


def test_login_failures_mark_the_provider_and_success_clears_it(monkeypatch):
    calls = []
    monkeypatch.setattr(stream.provider_runtime_status, "record_auth_failure", lambda p: calls.append(("fail", p)))
    monkeypatch.setattr(stream.provider_runtime_status, "clear", lambda p: calls.append(("clear", p)))
    code_of("not_logged_in.jsonl", returncode=1)
    run("happy.jsonl")
    assert calls == [("fail", "claude_cli"), ("clear", "claude_cli")]


def test_an_expired_credential_time_in_iso_form_means_login_expired():
    parser = stream.StreamParser(now=lambda: 1_900_000_000.0)
    parser.feed('{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}')
    parser.feed('{"type":"result","subtype":"success","is_error":true,"api_error_status":null,'
                '"credential_expires_at":"2026-12-21T03:45:55.867Z","result":"Request failed"}')
    with pytest.raises(stream.ClaudeCliError) as err:
        parser.finish(returncode=1, stderr_tail="")
    assert err.value.code == "login_expired"


def test_a_future_credential_time_does_not_change_the_code():
    parser = stream.StreamParser(now=lambda: 1_700_000_000.0)
    parser.feed('{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}')
    parser.feed('{"type":"result","subtype":"success","is_error":true,"api_error_status":403,'
                '"credential_expires_at":"2026-12-21T03:45:55.867Z","result":"Forbidden"}')
    with pytest.raises(stream.ClaudeCliError) as err:
        parser.finish(returncode=1, stderr_tail="")
    assert err.value.code == "org_policy"


def test_our_tools_failing_to_start_stops_the_turn_with_its_own_message():
    parser = stream.StreamParser()
    init = {"type": "system", "subtype": "init", "tools": [], "claude_code_version": "2.1.330",
            "mcp_servers": [{"name": "olga-companion", "status": "failed", "source": "dynamic"}]}
    with pytest.raises(stream.ClaudeCliError) as err:
        parser.feed(json.dumps(init))
    assert err.value.code == "tools_unavailable"
    assert "도구" in err.value.text("ko") and "tools" in err.value.text("en")
