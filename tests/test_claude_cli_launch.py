"""What the CLI is started with: the user's own sign-in environment, no app secrets, a private config."""

from __future__ import annotations

import json
import os
import time

import pytest

from olga_companion.llm import claude_cli_launch as launch

USER_ENV = {
    "USERPROFILE": "C:\\Users\\홍 길동",
    "HOME": "C:\\Users\\홍 길동",
    "APPDATA": "C:\\Users\\홍 길동\\AppData\\Roaming",
    "LOCALAPPDATA": "C:\\Users\\홍 길동\\App Data\\Local",
    "PATH": "C:\\Windows\\System32",
    "SystemRoot": "C:\\Windows",
    "ANTHROPIC_API_KEY": "user-own-key",
    "OLGA_BRIDGE_SECRET": "must-not-leak",
    "OLGA_SESSION_TOKEN": "must-not-leak",
    "olga_lower": "must-not-leak",
    "HTTPS_PROXY": "http://user-proxy:1",
}


def test_env_keeps_the_users_own_sign_in_and_drops_app_secrets():
    env = launch.build_env(USER_ENV, bundle_dir=None, proxy=None)
    for name in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "PATH", "SystemRoot", "ANTHROPIC_API_KEY"):
        assert env[name] == USER_ENV[name]
    assert not [k for k in env if k.upper().startswith("OLGA_")]
    assert "must-not-leak" not in json.dumps(env)


def test_without_the_app_proxy_the_users_own_proxy_settings_stay():
    env = launch.build_env(USER_ENV, bundle_dir=None, proxy=None)
    assert env["HTTPS_PROXY"] == "http://user-proxy:1"
    assert "NO_PROXY" not in env


def test_the_app_proxy_is_passed_on_and_loopback_is_never_proxied():
    env = launch.build_env(USER_ENV, bundle_dir=None, proxy="http://10.0.0.5:3128")
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == "http://10.0.0.5:3128"
    assert "127.0.0.1" in env["NO_PROXY"] and "localhost" in env["NO_PROXY"]


def test_mcp_config_holds_the_secret_and_port_and_only_our_server(tmp_path):
    with launch.run_files("turn-secret", 8899, root=tmp_path, harden=lambda p, directory: None) as files:
        data = json.loads(files.mcp_config.read_text(encoding="utf-8"))
        assert list(data["mcpServers"]) == ["olga-companion"]
        server = data["mcpServers"]["olga-companion"]
        assert server["env"] == {"OLGA_BRIDGE_SECRET": "turn-secret", "OLGA_SIDECAR_PORT": "8899"}
        assert server["command"] and isinstance(server["args"], list)
        assert files.run_dir.parent == tmp_path
        run_dir = files.run_dir
    assert not run_dir.exists()


def test_files_are_removed_after_an_error(tmp_path):
    with pytest.raises(RuntimeError):
        with launch.run_files("s", 1, root=tmp_path, harden=lambda p, directory: None) as files:
            kept = files.run_dir
            raise RuntimeError("boom")
    assert not kept.exists()


def test_no_launch_when_the_folder_cannot_be_made_private(tmp_path):
    def refuse(path, directory):
        raise OSError("acl")

    with pytest.raises(launch.LaunchError):
        with launch.run_files("s", 1, root=tmp_path, harden=refuse):
            pytest.fail("must not get here")
    assert list(tmp_path.iterdir()) == []


def test_korean_and_spaced_paths_make_valid_json(tmp_path):
    root = tmp_path / "테스트 사용자 name" / "App Data"
    with launch.run_files("s", 1, root=root, harden=lambda p, directory: None) as files:
        json.loads(files.mcp_config.read_text(encoding="utf-8"))
        assert "테스트 사용자 name" in str(files.mcp_config)


def test_stale_run_folders_are_swept(tmp_path):
    old = tmp_path / "run-old"
    old.mkdir()
    (old / "mcp.json").write_text("{}", encoding="utf-8")
    new = tmp_path / "run-new"
    new.mkdir()
    past = time.time() - 7200
    os.utime(old, (past, past))
    launch.sweep_stale(root=tmp_path)
    assert not old.exists() and new.exists()


def test_a_cancelled_turn_still_removes_its_folder(tmp_path):
    import asyncio

    seen = {}

    async def turn():
        with launch.run_files("s", 1, root=tmp_path, harden=lambda p, directory: None) as files:
            seen["dir"] = files.run_dir
            await asyncio.sleep(30)

    async def go():
        task = asyncio.create_task(turn())
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert not seen["dir"].exists()


def test_sweep_without_a_folder_yet_is_quiet(tmp_path):
    launch.sweep_stale(root=tmp_path / "missing")


def test_the_sidecar_sweeps_old_run_folders_at_start():
    from pathlib import Path

    source = (Path(launch.__file__).parents[1] / "sidecar.py").read_text(encoding="utf-8")
    assert "claude_cli_launch.sweep_stale()" in source


def test_a_failed_config_write_is_a_launch_error_and_leaves_nothing(tmp_path, monkeypatch):
    from pathlib import Path

    def full_disk(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", full_disk)
    with pytest.raises(launch.LaunchError):
        with launch.run_files("s", 1, root=tmp_path, harden=lambda p, directory: None):
            pass
    assert not list(tmp_path.glob("run-*"))


def test_cancelling_while_the_folder_is_being_made_leaves_nothing(tmp_path):
    import asyncio

    def slow_harden(_path, directory):
        time.sleep(0.3)

    async def go():
        async def use():
            async with launch.run_files_async("s", 1, root=tmp_path, harden=slow_harden):
                await asyncio.sleep(10)

        task = asyncio.create_task(use())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.6)

    asyncio.run(go())
    assert not list(tmp_path.glob("run-*"))
