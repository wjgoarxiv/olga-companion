from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import native_dialogs


@pytest.fixture(autouse=True)
def _available_test_wslinterop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "WSLInterop"
    marker.write_text("enabled")
    monkeypatch.setattr(native_dialogs, "WSL_INTEROP_PATH", marker)
