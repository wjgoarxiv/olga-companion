"""Small sidecar hardening items from the security review (B5, B6, B7, B11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import olga_companion.sidecar as sidecar
from olga_companion import sidecar_core_routes
from olga_companion.agent import pending_approvals, session_token

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("token", ["é" * 43, "\u2603", "a\x00b"])
def test_non_ascii_token_is_refused_not_a_crash(token: str) -> None:
    assert session_token.verify(token) is False


def test_the_real_token_still_verifies() -> None:
    assert session_token.verify(session_token.boot_token()) is True


def test_health_carries_no_install_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    exe = "C:\\Program Files\\Schlumberger\\OLGA 2022.1.0\\OlgaExecutables\\OLGA-2022.1.0.exe"
    monkeypatch.setattr(
        sidecar,
        "_all_capabilities",
        lambda: {
            "live_olga_run": {
                "enabled": True,
                "reason": "found",
                "reason_params": {"exe": exe},
                "candidates": [{"exe": "/mnt/c/Program Files/Schlumberger/OLGA 2022.1.0/x.exe"}],
            }
        },
    )
    monkeypatch.setattr(sidecar, "toolkit_status", lambda: {"found": True, "path": "\\\\server\\share\\toolkit"})
    body = json.dumps(sidecar_core_routes.health())
    assert "Program Files" not in body
    assert "Schlumberger" not in body
    assert "server" not in body
    assert "OLGA-2022.1.0.exe" in body


def test_api_docs_are_off_in_the_packaged_build() -> None:
    assert sidecar.api_docs_kwargs(frozen=True) == {"docs_url": None, "redoc_url": None, "openapi_url": None}
    assert sidecar.api_docs_kwargs(frozen=False) == {}


def test_bridge_cards_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pending_approvals.approval_journal, "commit", lambda *_a, **_k: None)
    monkeypatch.setattr(pending_approvals, "_PENDING", {})
    monkeypatch.setattr(pending_approvals, "_EXPIRES_EPOCH", {})
    for index in range(pending_approvals.BRIDGE_PENDING_CAP):
        pending_approvals.register(
            action_kind="genkey_save", args={}, call_id=f"bridge-{index}", context_generation=0, session_id="s"
        )
    with pytest.raises(pending_approvals.PendingApprovalError, match="outside tools"):
        pending_approvals.register(
            action_kind="genkey_save", args={}, call_id="bridge-extra", context_generation=0, session_id="s"
        )
    # The app's own chat cards are never blocked by an outside tool's flood.
    pending_approvals.register(action_kind="genkey_save", args={}, call_id="chat-1", context_generation=0, session_id="s")


def test_csp_blocks_base_form_and_framing() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    csp = config["app"]["security"]["csp"]
    for directive in ("base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'"):
        assert directive in csp


def test_health_route_still_answers() -> None:
    client = TestClient(sidecar.app)
    assert client.get("/health").status_code == 200
