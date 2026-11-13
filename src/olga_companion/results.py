from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Final

from .config import exports_root, toolkit_dir
from .genkey_static import OlgaInputError, file_sha256, run_tool
from .result_csv_exports import (
    export_selected_series_csv as _export_selected_series_csv,
    extract_csv as _extract_csv,
)
from .result_export_paths import require_export_path as _require_export_path
from .result_index import parse_index, parse_json as _parse_json
from .result_plot_exports import plot_result as _plot_result
from .result_provenance import ensure_result_source_unchanged
from .result_selection import (
    NAME_TOKEN,
    positions_equivalent as _positions_equivalent,
    require_tokens as _require_tokens,
)
from .result_series_view import apply_series_view
from .workspace import resolve_result
from .publication_plot import publication_renderer_status, render_publication_series

RESULT_SCRIPTS = {
    "result_parser": "result_parser.py",
    "fast_plotter": "fast_plotter.py",
    "fast_ppl_plotter": "fast_ppl_plotter.py",
    "data_exporter": "data_exporter.py",
}

SMOKE_FIXTURE = Path(__file__).with_name("resources") / "results" / "fixture.tpl"
PLOT_TIMEOUT_S = 120
# A real 1.4 MB .ppl needs ~81s just to list branches/timesteps; the 30s default
# timed out, so the first real file a user loaded reported ok=False.
RESULT_LOAD_TIMEOUT_S = 240
# Parsed index cached by schema, normalized suffix, and content sha256 — a repeat load is
# instant instead of re-paying the multi-second (.tpl) / ~minute (.ppl) parse.
# Bounded (LRU) so a long-lived sidecar with many re-runs can't grow without limit.
_LOAD_CACHE_CAP = 32
_LOAD_CACHE_SCHEMA_VERSION: Final = 1
_LOAD_CACHE: "OrderedDict[tuple[int, str, str], dict[str, Any]]" = OrderedDict()
_LOAD_CACHE_LOCK: Final = Lock()


def results_toolkit_status() -> dict[str, Any]:
    root = toolkit_dir()
    scripts = {name: (root / "scripts" / script).exists() for name, script in RESULT_SCRIPTS.items()}
    return {
        "toolkit_dir": str(root),
        "available": root.exists() and all(scripts.values()),
        "scripts": scripts,
    }


def _parse_index(path: Path) -> dict[str, Any]:
    return parse_index(
        path,
        run_tool=run_tool,
        result_scripts=RESULT_SCRIPTS,
        timeout_s=RESULT_LOAD_TIMEOUT_S,
    )


def load_result(path_value: str) -> dict[str, Any]:
    path = resolve_result(path_value)
    before = file_sha256(path)
    cache_key = (_LOAD_CACHE_SCHEMA_VERSION, path.suffix.casefold().lstrip("."), before)
    with _LOAD_CACHE_LOCK:
        cached = _LOAD_CACHE.get(cache_key)
        if cached is not None:
            _LOAD_CACHE.move_to_end(cache_key)  # LRU: mark as recently used
    if cached is not None:
        index = cached
        from_cache = True
    else:
        index = _parse_index(path)
        from_cache = False
    after = ensure_result_source_unchanged(path, before, file_sha256)
    if not from_cache and index.get("ok"):  # only cache a clean, stable parse
        with _LOAD_CACHE_LOCK:
            _LOAD_CACHE[cache_key] = index
            while len(_LOAD_CACHE) > _LOAD_CACHE_CAP:
                _LOAD_CACHE.popitem(last=False)  # evict the least-recently-used
    return {
        **index,
        "path": str(path),
        "cached": from_cache,
        "source_sha256_before": before,
        "source_sha256_after": after,
        "source_mutated": False,
    }


def _parser_position(selector: str) -> str:
    """The name the parser's catalog holds: an index label such as
    "BRANCH - MAIN" or "SECTION - Br - MAIN - PIPE - ..." becomes "MAIN"."""
    parts = [part.strip() for part in selector.split(" - ")]
    if len(parts) == 2 and parts[0].casefold() in {"branch", "br"} and parts[1]:
        return parts[1]
    if parts[0].casefold() == "section":
        for key, value in zip(parts[1::2], parts[2::2]):
            if key.casefold() == "br" and value:
                return value
    return selector


def variable_series(
    path_value: str,
    variable: str,
    position: str | None = None,
    *,
    value_unit: str | None = None,
    time_unit: str | None = None,
    quantity_kind: str = "point",
    range_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A single variable's time series `{time, values, unit, description}` — the JSON
    the interactive .tpl trend chart plots. Read-only."""
    path = resolve_result(path_value)
    if not NAME_TOKEN.fullmatch(variable) or variable.startswith("-"):
        raise OlgaInputError(f"Invalid variable name: {variable!r}")
    args = [str(path), "-v", variable, "--json"]
    position_selector = None
    if position:
        if any(ord(char) < 32 for char in position) or position.startswith("-"):
            raise OlgaInputError(f"Invalid result position: {position!r}")
        position_selector = position.removeprefix("POSITION - ").strip()
        parser_position = _parser_position(position_selector)
        if not parser_position or parser_position.startswith("-"):
            raise OlgaInputError(f"Invalid result position: {position!r}")
        args.extend(["--position", parser_position])
    before = file_sha256(path)
    command = run_tool("result_parser", args, timeout_s=RESULT_LOAD_TIMEOUT_S, names=RESULT_SCRIPTS)
    parsed = _parse_json(command.stdout)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("time"), list):
        raise OlgaInputError(f"Could not read a series for {variable!r} from {path.name}.")
    if position_selector and not _positions_equivalent(position_selector, str(parsed.get("position", ""))):
        raise OlgaInputError(
            f"Result parser returned position {parsed.get('position')!r}, expected {position_selector!r}."
        )
    values = parsed.get("values") or []
    try:
        viewed = apply_series_view(
            parsed["time"],
            values,
            source_unit=parsed.get("unit"),
            source_time_unit=parsed.get("time_unit"),
            value_unit=value_unit,
            time_unit=time_unit,
            quantity_kind=quantity_kind,
            range_spec=range_spec,
        )
    except ValueError as exc:
        raise OlgaInputError(str(exc)) from exc
    ensure_result_source_unchanged(path, before, file_sha256)
    return {
        "path": str(path),
        "variable": variable,
        "unit": viewed["unit"],
        "description": parsed.get("description"),
        "position": parsed.get("position"),
        "time": viewed["time"],
        "values": viewed["values"],
        "time_unit": viewed["time_unit"],
        "analysis": viewed["analysis"],
        "view": viewed["view"],
    }


def variable_profile(
    path_value: str,
    variable: str,
    branch: str,
    timestep: float | None = None,
) -> dict[str, Any]:
    """A single variable's spatial profile `{positions, values, unit}` for one
    branch at one time — the JSON the interactive .ppl profile chart plots.

    Trends (`variable_series`) answer "how does this change over time at a
    point"; a profile answers "how is this distributed along the branch at a
    time". Read-only.
    """
    path = resolve_result(path_value)
    if not NAME_TOKEN.fullmatch(variable) or variable.startswith("-"):
        raise OlgaInputError(f"Invalid variable name: {variable!r}")
    if (
        not branch
        or branch.startswith("-")
        or any(ord(char) < 32 for char in branch)
    ):
        raise OlgaInputError(f"Invalid result branch: {branch!r}")
    args = [str(path), "--variable", variable, "--branch", branch, "--json"]
    if timestep is not None:
        if not isinstance(timestep, (int, float)) or timestep != timestep:
            raise OlgaInputError(f"Invalid timestep: {timestep!r}")
        args.extend(["--timestep", repr(float(timestep))])
    before = file_sha256(path)
    command = run_tool(
        "result_parser", args, timeout_s=RESULT_LOAD_TIMEOUT_S, names=RESULT_SCRIPTS
    )
    parsed = _parse_json(command.stdout)
    if (
        not isinstance(parsed, dict)
        or not isinstance(parsed.get("positions"), list)
        or not isinstance(parsed.get("values"), list)
    ):
        raise OlgaInputError(
            f"Could not read a {variable!r} profile for branch {branch!r} "
            f"from {path.name}."
        )
    if len(parsed["positions"]) != len(parsed["values"]):
        raise OlgaInputError(
            f"Profile for {variable!r} returned "
            f"{len(parsed['positions'])} positions and "
            f"{len(parsed['values'])} values."
        )
    ensure_result_source_unchanged(path, before, file_sha256)
    return {
        "path": str(path),
        "variable": variable,
        "branch": parsed.get("branch", branch),
        "timestep": parsed.get("timestep"),
        "timestep_unit": parsed.get("timestep_unit"),
        "positions": parsed["positions"],
        "values": parsed["values"],
        "unit": parsed.get("unit"),
        "description": parsed.get("description"),
    }


def export_selected_series_csv(
    path_value: str,
    variable: str,
    position: str,
    *,
    value_unit: str | None = None,
    time_unit: str | None = None,
    quantity_kind: str = "point",
    range_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export exactly the position-selected series returned by ``variable_series``."""
    return _export_selected_series_csv(
        path_value,
        variable,
        position,
        value_unit=value_unit,
        time_unit=time_unit,
        quantity_kind=quantity_kind,
        range_spec=range_spec,
        resolve_result=resolve_result,
        hash_file=file_sha256,
        exports_root=exports_root,
        series_reader=variable_series,
    )


def extract_csv(
    path_value: str,
    variables: list[str],
    branch: str | None = None,
    timestep: float | None = None,
) -> dict[str, Any]:
    return _extract_csv(
        path_value,
        variables,
        branch,
        timestep,
        resolve_result=resolve_result,
        hash_file=file_sha256,
        exports_root=exports_root,
        require_tokens=_require_tokens,
        run_tool=run_tool,
        result_scripts=RESULT_SCRIPTS,
    )


def plot_result(
    path_value: str,
    variables: list[str] | None = None,
    branch: str | None = None,
    position: str | None = None,
    *,
    value_unit: str | None = None,
    time_unit: str | None = None,
    quantity_kind: str = "point",
    range_spec: dict[str, Any] | None = None,
    timestep: float | None = None,
) -> dict[str, Any]:
    return _plot_result(
        path_value,
        variables,
        branch,
        position,
        value_unit=value_unit,
        time_unit=time_unit,
        quantity_kind=quantity_kind,
        range_spec=range_spec,
        timestep=timestep,
        resolve_result=resolve_result,
        hash_file=file_sha256,
        exports_root=exports_root,
        require_tokens=_require_tokens,
        series_reader=variable_series,
        publication_renderer=render_publication_series,
        run_tool=run_tool,
        result_scripts=RESULT_SCRIPTS,
        plot_timeout_s=PLOT_TIMEOUT_S,
    )


def require_export_path(path_value: str) -> Path:
    return _require_export_path(path_value, exports_root=exports_root)


@lru_cache(maxsize=1)
def _fixture_smoke() -> tuple[bool, str]:
    if not results_toolkit_status()["available"]:
        return False, "Required result toolkit scripts are missing."
    if not SMOKE_FIXTURE.exists():
        return False, f"Representative fixture missing: {SMOKE_FIXTURE}"
    command = run_tool("result_parser", [str(SMOKE_FIXTURE), "--list-vars", "--json"], names=RESULT_SCRIPTS)
    if command.exit_code != 0:
        detail = command.stderr.strip().splitlines()[-1] if command.stderr.strip() else "parser failed"
        return False, f"Fixture smoke-parse failed (pyfas installed?): {detail}"
    return True, "Result parser verified against the representative fixture."


def result_capabilities() -> dict[str, Any]:
    enabled, reason = _fixture_smoke()
    return {
        "result_analysis": {"enabled": enabled, "reason": reason},
        "publication_export": publication_renderer_status(),
    }
