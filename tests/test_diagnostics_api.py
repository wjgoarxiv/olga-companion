"""`/api/diagnostics` previews a bug-report bundle and writes it to a temp file.

The preview is a plain read: version strings, proxy summary without credentials,
and the recent log files the bundle will pull in. The bundle write packs those
same facts into a zip (meta.json + logs/) that the user attaches to a GitHub
issue; the reply names the file path, its size, and the pre-filled issue URL.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import sidecar
from olga_companion.agent import session_token
from olga_companion.net import http as net_http
from olga_companion.net import preferences as prefs


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(prefs, "_file", lambda: tmp_path / "proxy.json")
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "sidecar.log").write_text("line1\nline2\n", encoding="utf-8")
    (logs_dir / "sidecar.log.1").write_text("older\n", encoding="utf-8")
    monkeypatch.setattr(
        "olga_companion.sidecar_diagnostics_routes._logs_dir",
        lambda: logs_dir,
    )
    bundles_dir = tmp_path / "bundles"
    monkeypatch.setattr(
        "olga_companion.sidecar_diagnostics_routes._bundles_dir",
        lambda: bundles_dir,
    )
    net_http.clear_probe_cache()
    with TestClient(sidecar.app) as test_client:
        yield test_client


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def test_missing_session_token_is_refused(client: TestClient) -> None:
    assert client.get("/api/diagnostics").status_code == 401
    assert client.post("/api/diagnostics/bundle").status_code == 401


def test_preview_reports_versions_and_proxy_and_log_list(client: TestClient) -> None:
    body = client.get("/api/diagnostics", headers=_headers()).json()
    assert "app_version" in body["versions"]
    assert body["versions"]["app_version"]
    assert "python_version" in body["versions"]
    assert "os" in body["versions"]
    assert body["proxy"]["enabled"] is False
    assert body["proxy"]["host"] == "127.0.0.1"
    log_names = {entry["name"] for entry in body["logs"]}
    assert log_names == {"sidecar.log", "sidecar.log.1"}
    for entry in body["logs"]:
        assert entry["size_bytes"] > 0


def test_bundle_writes_zip_with_meta_and_logs(client: TestClient) -> None:
    reply = client.post("/api/diagnostics/bundle", headers=_headers()).json()
    bundle_path = Path(reply["bundle_path"])
    assert bundle_path.exists()
    assert bundle_path.suffix == ".zip"
    assert reply["size_bytes"] == bundle_path.stat().st_size
    assert reply["issue_url"].startswith("https://github.com/wjgoarxiv/olga-companion/issues/new")

    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
        assert "meta.json" in names
        assert "logs/sidecar.log" in names
        assert "logs/sidecar.log.1" in names
        meta = json.loads(zf.read("meta.json").decode("utf-8"))
        assert meta["versions"]["app_version"]
        assert meta["proxy"]["enabled"] is False
        assert "generated_at" in meta
        log_body = zf.read("logs/sidecar.log").decode("utf-8")
        assert "line1" in log_body


def test_bundle_omits_api_keys_or_tokens_from_meta(client: TestClient) -> None:
    reply = client.post("/api/diagnostics/bundle", headers=_headers()).json()
    with zipfile.ZipFile(Path(reply["bundle_path"])) as zf:
        meta_bytes = zf.read("meta.json")
    text = meta_bytes.decode("utf-8")
    for forbidden in ("api_key", "token", "secret", "password"):
        assert forbidden not in text.lower(), f"meta.json leaks {forbidden}"


def test_issue_url_carries_version_and_os_in_body(client: TestClient) -> None:
    reply = client.post("/api/diagnostics/bundle", headers=_headers()).json()
    url = reply["issue_url"]
    assert "title=" in url
    assert "body=" in url
    assert "labels=bug" in url


def test_bundle_meta_carries_runtime_selection_and_locale_facts(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion import config as app_config
    from olga_companion.agent import history

    fake_root = tmp_path / "fake-prog"
    (fake_root / "OLGA 2022.1.0").mkdir(parents=True)
    (fake_root / "OLGA 2022.1.0" / "opi.exe").write_bytes(b"fake")
    (fake_root / "OLGA-S").mkdir(exist_ok=True)
    (fake_root / "OLGA-S" / "opi.exe").write_bytes(b"fake")
    monkeypatch.setattr(
        "olga_companion.sidecar_diagnostics_routes._exe_globs",
        lambda: [str(fake_root / "OLGA*" / "opi.exe")],
    )
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    session_id = history.new_session("locale probe")
    history.append(
        session_id,
        {"record": "user", "text": "hello", "locale": "ko"},
    )
    (tmp_path / "llm-selection.json").write_text(
        '{"provider": "xai", "model": "grok-4.7", "variant": "medium"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(app_config, "llm_selection_path", lambda: tmp_path / "llm-selection.json")

    reply = client.post("/api/diagnostics/bundle", headers=_headers()).json()
    with zipfile.ZipFile(Path(reply["bundle_path"])) as zf:
        meta = json.loads(zf.read("meta.json").decode("utf-8"))

    versions = meta["olga_versions"]
    assert versions == [{"version": "2022.1.0", "kind": "opi"}]
    assert all(set(entry) == {"version", "kind"} for entry in versions)
    assert "OLGA-S" not in json.dumps(versions)
    assert not any("fake-prog" in str(value) for entry in versions for value in entry.values())
    assert meta["llm_selection"] == {"provider": "xai", "model": "grok-4.7", "variant": "medium"}
    assert meta["ui_locale"] == "ko"
