from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Final, TypeGuard

from .case_spec_validation import JsonValue
from .patrol_sanitization import bounded_diagnostic_items, safe_diagnostic_text

_MAX_TEXT, _MAX_TAIL = 400, 1200


@dataclass(frozen=True, slots=True)
class PatrolDependencies:
    run_status: Callable[[str], dict[str, JsonValue]]
    monitor_snapshot: Callable[[str, str | None], dict[str, JsonValue]]
    diagnose_out: Callable[[str], dict[str, JsonValue]]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]


@dataclass(frozen=True, slots=True)
class PatrolInputError(ValueError):
    field: str
    detail: str

    def __str__(self) -> str:
        return f"{self.field}: {self.detail}"


@dataclass(slots=True)
class _PatrolRegistry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    active: set[str] = field(default_factory=set)

    def claim(self, run_id: str) -> bool:
        with self.lock:
            if run_id in self.active:
                return False
            self.active.add(run_id)
            return True

    def release(self, run_id: str) -> None:
        with self.lock:
            self.active.discard(run_id)


_REGISTRY: Final = _PatrolRegistry()


def _default_dependencies() -> PatrolDependencies:
    from . import diagnostics, runner

    return PatrolDependencies(
        run_status=runner.run_status,
        monitor_snapshot=diagnostics.monitor_snapshot,
        diagnose_out=diagnostics.diagnose_out,
        monotonic=time.monotonic,
        sleep=time.sleep,
    )


def _is_map(value: JsonValue | None) -> TypeGuard[dict[str, JsonValue]]:
    return isinstance(value, dict)


def _is_list(value: JsonValue | None) -> TypeGuard[list[JsonValue]]:
    return isinstance(value, list)


def _text(value: JsonValue | None, limit: int = _MAX_TEXT) -> str | None:
    return value[:limit] if isinstance(value, str) else None


def _number(value: JsonValue | None) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _private_paths(status: dict[str, JsonValue]) -> tuple[str | None, str | None]:
    run_dir = _text(status.get("run_dir"), 4096)
    if run_dir is None:
        return None, None
    root = Path(run_dir).expanduser().resolve()
    progress = status.get("solver_progress")
    files = progress.get("files") if _is_map(progress) else None
    out_name = _text(files.get("out"), 255) if _is_map(files) else None
    log_name = _text(files.get("run_log"), 255) if _is_map(files) else None
    if out_name is None:
        outputs = status.get("outputs")
        if _is_list(outputs):
            for item in outputs:
                if _is_map(item) and _text(item.get("suffix")) == ".out":
                    out_name = _text(item.get("name"), 255)
                    if out_name is None:
                        explicit = _text(item.get("path"), 4096)
                        out_name = Path(explicit).name if explicit is not None else None
                    break
    if out_name is None or Path(out_name).name != out_name or Path(out_name).suffix.lower() != ".out":
        return None, None
    out_path = (root / out_name).resolve()
    if out_path.parent != root:
        return None, None
    safe_log = log_name if log_name is not None and Path(log_name).name == log_name else "run.log"
    return str(out_path), str(root / safe_log)


def _public_outputs(status: dict[str, JsonValue]) -> list[JsonValue]:
    public: list[JsonValue] = []
    outputs = status.get("outputs")
    if not _is_list(outputs):
        return public
    for item in outputs[:50]:
        if not _is_map(item):
            continue
        name = _text(item.get("name"), 255)
        suffix = _text(item.get("suffix"), 16)
        if name is not None and Path(name).name == name and suffix is not None:
            public.append({"name": name, "suffix": suffix})
    return public


def _progress(status: dict[str, JsonValue], deps: PatrolDependencies) -> dict[str, JsonValue]:
    out_path, log_path = _private_paths(status)
    if out_path is not None:
        return deps.monitor_snapshot(out_path, log_path)
    progress = status.get("solver_progress")
    return progress if _is_map(progress) else {}


def _observation(status: dict[str, JsonValue], progress: dict[str, JsonValue]) -> dict[str, JsonValue]:
    state = _text(status.get("state")) or "unknown"
    item: dict[str, JsonValue] = {"state": state}
    elapsed_ms = _number(status.get("elapsed_ms"))
    if elapsed_ms is not None and elapsed_ms >= 0:
        item["elapsed_s"] = round(elapsed_ms / 1000.0, 3)
    for key in ("phase", "liveness", "parse_status", "activity_status"):
        value = _text(progress.get(key))
        if value is not None:
            item[key] = value
    for key in ("simulation_time_s", "step", "adaptive_total_steps", "step_size_s"):
        value = _number(progress.get(key))
        if value is not None and value >= 0:
            item[key] = value
    vendor_percent = _number(progress.get("vendor_percent"))
    if vendor_percent is not None and 0 <= vendor_percent <= 100:
        item["vendor_percent"] = vendor_percent
        item["fraction"] = vendor_percent / 100.0
    return item


def _diagnose(out_path: str | None, deps: PatrolDependencies) -> tuple[JsonValue, JsonValue]:
    if out_path is None:
        return {"ok": False, "reason": "solver_output_unavailable"}, None
    raw = deps.diagnose_out(out_path)
    issues = bounded_diagnostic_items(raw.get("issues"), _MAX_TEXT)
    suggestions = bounded_diagnostic_items(raw.get("suggestions"), _MAX_TEXT)
    singular_issue = _text(raw.get("issue"))
    singular_suggestion = _text(raw.get("suggestion"))
    if singular_suggestion is not None and not suggestions:
        suggestions = [singular_suggestion]
    diagnosis: dict[str, JsonValue] = {
        "ok": raw.get("ok") is True,
        "issue_count": len(issues),
        "issues": issues,
        "suggestions": suggestions,
    }
    if singular_issue is not None:
        diagnosis["issue"] = singular_issue
    if not suggestions:
        return diagnosis, None
    proposal: dict[str, JsonValue] = {
        "summary": suggestions[0],
        "supported_case_edit": False,
        "requires_fresh_approval": True,
        "auto_apply": False,
        "auto_rerun": False,
    }
    return diagnosis, proposal


def _response(run_id: str) -> dict[str, JsonValue]:
    return {
        "run_id": run_id[:128],
        "terminal": False,
        "state": "uncertain",
        "stop_reason": "unknown",
        "polls": 0,
        "elapsed_s": 0.0,
        "recovered_from_receipt": False,
        "observations": [],
        "anomaly": None,
        "diagnosis": None,
        "proposal": None,
        "evidence": {"tail": ""},
        "outputs": [],
        "actions_dispatched": [],
    }


def patrol_run(
    run_id: str,
    *,
    deadline_s: float,
    max_polls: int,
    backoff_s: float,
    dependencies: PatrolDependencies | None = None,
) -> dict[str, JsonValue]:
    finite_bounds = math.isfinite(deadline_s) and math.isfinite(backoff_s)
    if not run_id or not finite_bounds or deadline_s <= 0 or not 1 <= max_polls <= 256 or not 0 <= backoff_s <= 60:
        raise PatrolInputError("request", "bounded patrol values are invalid")
    result = _response(run_id)
    if not _REGISTRY.claim(run_id):
        result.update({"state": "patrol_active", "stop_reason": "single_flight"})
        return result
    deps = dependencies or _default_dependencies()
    started = deps.monotonic()
    try:
        for poll_index in range(max_polls):
            elapsed = max(0.0, deps.monotonic() - started)
            if poll_index > 0 and elapsed >= deadline_s:
                result.update({"state": "uncertain", "stop_reason": "deadline", "elapsed_s": elapsed})
                return result
            status = deps.run_status(run_id)
            progress = _progress(status, deps)
            elapsed = max(0.0, deps.monotonic() - started)
            observations = result["observations"]
            if _is_list(observations):
                observations.append(_observation(status, progress))
            result["polls"] = poll_index + 1
            result["elapsed_s"] = elapsed
            if elapsed >= deadline_s:
                result.update({"state": "uncertain", "stop_reason": "deadline"})
                return result
            result["recovered_from_receipt"] = bool(
                result["recovered_from_receipt"] or status.get("recovered_from_receipt") is True
            )
            result["outputs"] = _public_outputs(status)
            result["evidence"] = {
                "tail": safe_diagnostic_text(status.get("log_tail"), _MAX_TAIL)
            }
            state = _text(status.get("state")) or "unknown"
            if state == "completed" and (status.get("ok") is False or status.get("engine_failed") is True):
                state = "failed"
            match state:
                case "completed" | "cancelled" | "timed_out":
                    result.update({"terminal": True, "state": state, "stop_reason": "terminal"})
                    return result
                case "failed":
                    out_path, _log_path = _private_paths(status)
                    diagnosis, proposal = _diagnose(out_path, deps)
                    result.update(
                        {
                            "terminal": True,
                            "state": "failed",
                            "stop_reason": "terminal",
                            "anomaly": "terminal_failure",
                            "diagnosis": diagnosis,
                            "proposal": proposal,
                        }
                    )
                    return result
                case "supervision_unknown" | "recovery_unknown" | "receipt_error":
                    result.update({"state": "uncertain", "stop_reason": state})
                    return result
                case "running" | "finalizing":
                    result.update({"state": state, "stop_reason": "poll_limit"})
                case _:
                    result.update({"state": "uncertain", "stop_reason": "unknown_state"})
                    return result
            if poll_index + 1 < max_polls:
                remaining = deadline_s - max(0.0, deps.monotonic() - started)
                if remaining <= 0:
                    result.update({"state": "uncertain", "stop_reason": "deadline"})
                    return result
                deps.sleep(min(backoff_s, remaining))
        return result
    finally:
        _REGISTRY.release(run_id)
