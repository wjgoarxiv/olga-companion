"""What Settings shows for the local CLI: whether it was found, and a Check the user starts.

Status never runs a model request. Check sends one tiny prompt with no app tools at all and
reports the result code, the version and how the user's Claude Code is billed (its own
sign-in or its own API key; this app never sees either).
"""

from __future__ import annotations

import asyncio

from typing import Any

from . import claude_cli_discovery, claude_cli_launch, claude_cli_process, claude_cli_stream

CHECK_PROMPT = "Reply with the single word OK."
CHECK_LIMITS = claude_cli_process.Limits(first_event_s=60.0, idle_s=60.0, total_s=120.0)

_DIAGNOSIS: dict[str, tuple[str, str]] = {
    "ok": ("이 PC에서 Claude Code를 찾았습니다.", "Claude Code was found on this PC."),
    "not_installed": (
        "이 PC에서 Claude Code를 찾지 못했습니다. Windows에 Claude Code를 설치한 뒤 \"다시 찾기\"를 누르세요.",
        "Claude Code was not found on this PC. Install it on Windows, then select \"Find again\".",
    ),
    "override_missing": (
        "저장해 둔 Claude Code 실행 파일 위치에 파일이 없습니다. Claude Code를 다시 설치한 뒤 \"다시 찾기\"를 누르세요.",
        "The saved Claude Code location no longer has the program. Reinstall Claude Code, then select \"Find again\".",
    ),
    "not_executable": (
        "Claude Code 실행 파일을 실행하지 못했습니다. 보안 프로그램이 막고 있는지 확인하세요.",
        "The Claude Code executable could not be started. Check whether security software blocks it.",
    ),
    "probe_timeout": (
        "Claude Code가 버전 확인에 응답하지 않았습니다. 잠시 뒤 다시 확인하세요.",
        "Claude Code did not answer the version check. Try again in a moment.",
    ),
    "version_too_old": (
        "Claude Code 버전이 너무 오래되었습니다. `claude update`로 업데이트하세요.",
        "This Claude Code is too old. Update it with `claude update`.",
    ),
    "flags_missing": (
        "이 Claude Code 버전에는 필요한 옵션이 없습니다. `claude update`로 업데이트하세요.",
        "This Claude Code version lacks options the app needs. Update it with `claude update`.",
    ),
    "cmd_shim_unsafe": (
        "Claude Code 설치 경로에 특수 문자가 있어 안전하게 실행할 수 없습니다. 네이티브 설치(claude.exe)를 쓰세요.",
        "The Claude Code install path has special characters, so it cannot be started safely. Use the native install (claude.exe).",
    ),
}
DIAGNOSES: tuple[str, ...] = tuple(_DIAGNOSIS)


def diagnosis(code: str, locale: str) -> str:
    ko, en = _DIAGNOSIS.get(code, _DIAGNOSIS["not_installed"])
    return ko if locale == "ko" else en


def _messages(code: str) -> dict[str, str]:
    if code in _DIAGNOSIS:
        return {"message_ko": diagnosis(code, "ko"), "message_en": diagnosis(code, "en")}
    return {"message_ko": claude_cli_stream.message(code, "ko"), "message_en": claude_cli_stream.message(code, "en")}


def status(fresh: bool = False) -> dict[str, Any]:
    if fresh:
        claude_cli_discovery.invalidate()
    found = claude_cli_discovery.resolve()
    return {"code": found.code, "version": found.version, "override": bool(claude_cli_discovery.load_override()),
            **_messages(found.code)}


def _billing(api_key_source: str) -> str:
    if not api_key_source:
        return "unknown"
    return "subscription" if api_key_source == "none" else "api_key"


async def check() -> dict[str, Any]:
    """One tiny request through the user's own Claude Code, with no app tools."""
    found = await asyncio.to_thread(claude_cli_discovery.resolve, use_cache=False)
    if found.code != "ok":
        return {"code": found.code, "version": found.version, "billing": "unknown", **_messages(found.code)}
    parser = claude_cli_stream.StreamParser()
    billing = "unknown"
    try:
        async with claude_cli_launch.run_files_async("", 0, with_tools=False) as files:
            argv = [*found.argv, "-p", "--tools", "", "--mcp-config", str(files.mcp_config), "--strict-mcp-config",
                    "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence",
                    "--output-format", "stream-json", "--verbose"]
            if found.argv[:1] == ["cmd.exe"] and not claude_cli_discovery.cmd_safe_args(argv[5:]):
                return {"code": "cmd_shim_unsafe", "version": found.version, "billing": billing,
                        **_messages("cmd_shim_unsafe")}
            process = claude_cli_process.CliProcess(argv, prompt=CHECK_PROMPT, env=claude_cli_launch.default_env(),
                                                    cwd=files.run_dir, limits=CHECK_LIMITS)
            async for line in process.lines():
                parser.feed(line)
                billing = _billing(parser.api_key_source) if billing == "unknown" else billing
            parser.finish(returncode=process.returncode, stderr_tail=process.stderr_tail)
    except claude_cli_stream.ClaudeCliError as err:
        return {"code": err.code, "version": found.version, "billing": billing, **_messages(err.code)}
    except claude_cli_process.CliProcessError as err:
        code = "crashed" if err.code == "launch_failed" else err.code
        return {"code": code, "version": found.version, "billing": billing, **_messages(code)}
    except claude_cli_launch.LaunchError:
        return {"code": "crashed", "version": found.version, "billing": billing, **_messages("crashed")}
    return {"code": "ok", "version": parser.version or found.version, "billing": billing,
            "message_ko": "Claude Code가 응답했습니다. 이 앱에서 쓸 수 있습니다.",
            "message_en": "Claude Code answered. It is ready to use in this app."}


def set_override(path: str | None) -> dict[str, Any]:
    if path:
        claude_cli_discovery.save_override(path)
    else:
        claude_cli_discovery.clear_override()
    return status()
