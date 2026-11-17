"""With a case open, the assistant works on that case and does not offer templates."""

from __future__ import annotations

import pytest

from olga_companion import workspace
from olga_companion.agent import runtime


def test_an_open_case_tells_the_assistant_to_work_on_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workspace, "active_workspace_rel", lambda: "lines/riser.genkey")
    text = runtime._system_instruction("BASE")
    assert "lines/riser.genkey" in text
    assert "Do not offer templates" in text
    assert "unless the user asks" in text


def test_without_an_open_case_templates_stay_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workspace, "active_workspace_rel", lambda: None)
    text = runtime._system_instruction("BASE")
    assert "Do not offer templates" not in text
    assert "No case is open" in text
