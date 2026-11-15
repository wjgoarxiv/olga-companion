from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

APP_NAME = "OLGA Companion"
FRONTEND_PORT = 5273
SIDECAR_PORT = 8865
# Development fallback only. Packaged builds always set OLGA_TOOLKIT_DIR to the
# bundled resource directory (src-tauri/src/main.rs), so this value is never read
# from a frozen binary. Resolved from this file rather than project_root() because
# project_root() is redirected to app-local data when OLGA_APP_DATA_DIR is set.
DEFAULT_TOOLKIT_DIR = Path(__file__).resolve().parents[2] / "resources" / "olga-toolkit"
# litellm "provider/model" convention; consumed by the Antigravity preview client.
DEFAULT_LLM_MODEL = os.getenv("OLGA_LLM_MODEL", "gemini/gemini-2.0-flash")


class WorkspaceContextError(ValueError):
    """The durable workspace context is malformed, missing after initialization, or unsafe."""


_WORKSPACE_CONTEXT_WRITE_LOCK = threading.Lock()
_CONTEXT_INITIALIZED_SEEN = False


def project_root() -> Path:
    packaged_root = os.environ.get("OLGA_APP_DATA_DIR")
    if packaged_root:
        return Path(packaged_root).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def sandbox_root() -> Path:
    root = project_root() / "var" / "sandbox"
    root.mkdir(parents=True, exist_ok=True)
    return root


def exports_root() -> Path:
    root = project_root() / "var" / "exports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def private_state_root() -> Path:
    return Path.home() / ".olga_copilot"


def toolkit_dir() -> Path:
    return Path(os.environ.get("OLGA_TOOLKIT_DIR", str(DEFAULT_TOOLKIT_DIR))).expanduser()


def native_tab_enabled() -> bool:
    """The in-app table generator exists only in local PVT builds that set the flag to 1."""
    return os.environ.get("OLGA_COMPANION_NATIVE_TAB") == "1"


def _workspace_override_path() -> Path:
    """Legacy root-only record retained only for first-use migration."""
    return project_root() / "var" / "workspace-root.json"


def _workspace_context_path() -> Path:
    return project_root() / "var" / "workspace-context.json"


def _workspace_context_marker_path() -> Path:
    return project_root() / "var" / "workspace-context.initialized"


def _parse_context_record(path: Path) -> tuple[Path, int]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceContextError(f"Workspace context record is malformed: {path}") from exc
    if not isinstance(record, dict):
        raise WorkspaceContextError("Workspace context record must be an object.")
    if set(record) != {"root", "generation"}:
        raise WorkspaceContextError("Workspace context record has invalid fields.")
    root_value = record.get("root")
    generation = record.get("generation")
    if not isinstance(root_value, str) or not root_value or any(ord(char) < 32 for char in root_value):
        raise WorkspaceContextError("Workspace context root is invalid.")
    root = Path(root_value).expanduser()
    if not root.is_absolute():
        raise WorkspaceContextError("Workspace context root must be absolute.")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        raise WorkspaceContextError("Workspace context generation is invalid.")
    return root.resolve(), generation


def _legacy_workspace_context() -> tuple[Path, int]:
    legacy = _workspace_override_path()
    if legacy.exists():
        try:
            record = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceContextError(f"Legacy workspace root record is malformed: {legacy}") from exc
        root_value = record.get("root") if isinstance(record, dict) else None
        if not isinstance(root_value, str) or not root_value or any(ord(char) < 32 for char in root_value):
            raise WorkspaceContextError("Legacy workspace root record is invalid.")
        return Path(root_value).expanduser().resolve(), 0
    return (project_root() / "var" / "workspace").resolve(), 0


def _stored_workspace_context() -> tuple[Path, int]:
    global _CONTEXT_INITIALIZED_SEEN
    path = _workspace_context_path()
    if path.exists():
        _CONTEXT_INITIALIZED_SEEN = True
        return _parse_context_record(path)
    if _workspace_context_marker_path().exists():
        _CONTEXT_INITIALIZED_SEEN = True
        raise WorkspaceContextError("Workspace context record is missing after initialization.")
    if _CONTEXT_INITIALIZED_SEEN:
        raise WorkspaceContextError("Workspace context record is missing after initialization in this process.")
    return _legacy_workspace_context()


def workspace_context() -> tuple[Path, int]:
    """Read one validated stored snapshot, then apply the fixed launch-time root override."""
    persisted = _stored_workspace_context()
    env = os.environ.get("OLGA_WORKSPACE_DIR")
    if env:
        return Path(env).expanduser().resolve(), 0
    return persisted


def _atomic_write(path: Path, payload: dict[str, str | int] | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            if isinstance(payload, str):
                handle.write(payload)
            else:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
        _fsync_parent_directory(path.parent)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def commit_workspace_context(root: Path | str, generation: int) -> tuple[Path, int]:
    """Atomically publish one root+generation record after caller-side invalidation."""
    resolved = Path(root).expanduser().resolve()
    if not resolved.is_dir():
        raise WorkspaceContextError(f"not a directory: {root}")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        raise WorkspaceContextError("Workspace context generation is invalid.")
    with _WORKSPACE_CONTEXT_WRITE_LOCK:
        _commit_workspace_context_unlocked(resolved, generation)
    return resolved, generation


def _commit_workspace_context_unlocked(resolved: Path, generation: int) -> None:
    global _CONTEXT_INITIALIZED_SEEN
    marker = _workspace_context_marker_path()
    if not marker.exists():
        _atomic_write(marker, "initialized\n")
        _CONTEXT_INITIALIZED_SEEN = True
    _atomic_write(_workspace_context_path(), {"root": str(resolved), "generation": generation})
    _CONTEXT_INITIALIZED_SEEN = True


def _fsync_parent_directory(parent: Path) -> None:
    from .sidecar_save_as_fsync import fsync_directory

    fsync_directory(parent)


def set_workspace_root(path: str) -> Path:
    """Compatibility setter: atomically replace root while preserving generation."""
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise WorkspaceContextError(f"not a directory: {path}")
    with _WORKSPACE_CONTEXT_WRITE_LOCK:
        _, generation = _stored_workspace_context()
        _commit_workspace_context_unlocked(p, generation)
    return p


class LlmSelectionError(ValueError):
    """The saved provider selection is missing a field or names an unknown provider."""


_LLM_SELECTION_FIELDS = ("provider", "model", "variant")
_LLM_PROVIDERS = frozenset({"openai", "copilot", "antigravity", "xai", "apikey"})
_LLM_VARIANTS = frozenset({"max", "xhigh", "high", "medium", "low"})
_LLM_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_EMPTY_LLM_SELECTION = {"provider": "", "model": "", "variant": ""}


def _verified_apikey_model(model: str) -> bool:
    """True when the model is a verified API-key connection the chat picker can offer."""
    from .llm.catalog import is_valid_model

    return is_valid_model("apikey", model)


def llm_selection_path() -> Path:
    """Non-secret operator choice. Credentials stay under the private home directory."""
    return project_root() / "var" / "llm-selection.json"


class OlgaExeOverrideError(ValueError):
    """The saved manual OLGA executable choice is missing or invalid."""


def olga_exe_override_path() -> Path:
    """Non-secret operator choice: the Settings-picked OLGA executable."""
    return project_root() / "var" / "olga-exe-override.json"


def load_olga_exe_override() -> str:
    """Return the saved manual executable path, or "" when none is saved."""
    path = olga_exe_override_path()
    if not path.is_file():
        return ""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    exe = record.get("exe") if isinstance(record, dict) else None
    return exe if isinstance(exe, str) else ""


def save_olga_exe_override(record: object) -> dict[str, str]:
    """Persist a manual OLGA executable choice. It must exist and be a file."""
    if not isinstance(record, dict):
        raise OlgaExeOverrideError("OLGA executable choice must be an object.")
    exe = record.get("exe")
    if not isinstance(exe, str) or not exe.strip() or any(ord(char) < 32 for char in exe):
        raise OlgaExeOverrideError("OLGA executable path is invalid.")
    candidate = Path(exe).expanduser()
    if not candidate.is_absolute():
        raise OlgaExeOverrideError("OLGA executable path must be absolute.")
    if not candidate.is_file():
        raise OlgaExeOverrideError("OLGA executable must be an existing file.")
    if candidate.suffix.lower() != ".exe":
        raise OlgaExeOverrideError("OLGA executable must be a .exe file.")
    resolved = str(candidate.resolve())
    _atomic_write(olga_exe_override_path(), {"exe": resolved})
    return {"exe": resolved}


def clear_olga_exe_override() -> bool:
    """Drop the saved manual choice; return True when one existed."""
    try:
        olga_exe_override_path().unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise OlgaExeOverrideError(f"Could not clear the OLGA choice: {exc}") from exc
    return True


def _validated_llm_selection(record: object, *, strict_keys: bool) -> dict[str, str]:
    if not isinstance(record, dict):
        raise LlmSelectionError("LLM selection must be an object.")
    if strict_keys and set(record) != set(_LLM_SELECTION_FIELDS):
        raise LlmSelectionError("LLM selection has invalid fields.")
    provider = record.get("provider")
    model = record.get("model")
    variant = record.get("variant")
    if not isinstance(provider, str) or provider not in _LLM_PROVIDERS:
        raise LlmSelectionError("LLM provider is not available.")
    if not isinstance(model, str) or _LLM_MODEL_RE.fullmatch(model) is None:
        raise LlmSelectionError("LLM model is invalid.")
    if provider == "apikey" and not _verified_apikey_model(model):
        raise LlmSelectionError("LLM model is invalid.")
    if not isinstance(variant, str) or variant not in _LLM_VARIANTS:
        raise LlmSelectionError("LLM variant is invalid.")
    return {"provider": provider, "model": model, "variant": variant}


def load_llm_selection() -> dict[str, str]:
    path = llm_selection_path()
    if not path.is_file():
        return dict(_EMPTY_LLM_SELECTION)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        return _validated_llm_selection(record, strict_keys=False)
    except (OSError, json.JSONDecodeError, LlmSelectionError):
        return dict(_EMPTY_LLM_SELECTION)


def save_llm_selection(record: object) -> dict[str, str]:
    selection = _validated_llm_selection(record, strict_keys=True)
    _atomic_write(llm_selection_path(), selection)
    return selection


def llm_selection_settings() -> dict[str, str | dict[str, str]]:
    """Shape expected by resolve_llm_selection. Empty when nothing is saved."""
    selection = load_llm_selection()
    provider = selection["provider"]
    if not provider:
        return {}
    return {
        "active_llm_provider": provider,
        "provider_models": {provider: selection["model"]},
        "active_llm_variant": selection["variant"],
    }


def workspace_root() -> Path:
    """The user's OLGA case workspace — where their `.genkey`/`.tab` files live and
    where the agent writes new cases. Precedence: `OLGA_WORKSPACE_DIR` env (launch /
    tests) → a UI-set override (`var/workspace-root.json`) → default `var/workspace`.
    This is the containment boundary for the workspace API: no path outside this root
    is ever listed, activated, or written. (Fulfils the NORTHSTAR "no path typing"
    promise — set once, then discover files inside it.)"""
    root, _ = workspace_context()
    root.mkdir(parents=True, exist_ok=True)
    return root
