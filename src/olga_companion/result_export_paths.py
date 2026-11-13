from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .genkey_static import OlgaInputError

ExportsRoot = Callable[[], Path]


def create_export_dir(exports_root: ExportsRoot) -> Path:
    path = exports_root() / "results" / uuid.uuid4().hex[:12]
    path.mkdir(parents=True, exist_ok=False)
    return path


def safe_export_token(value: Any, fallback: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._-")
    return (token or fallback)[:64]


def require_export_path(path_value: str, *, exports_root: ExportsRoot) -> Path:
    if not path_value or not path_value.strip():
        raise OlgaInputError("A file path is required.")
    path = Path(path_value).expanduser().resolve()
    root = exports_root().resolve()
    if root not in path.parents:
        raise OlgaInputError("Only files under var/exports can be downloaded.")
    if not path.is_file():
        raise OlgaInputError(f"File not found: {path}")
    return path
