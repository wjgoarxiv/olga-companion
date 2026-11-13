"""Bundled example cases: list the ones that validate, install one without overwriting.

An example reaches the gallery only when it compiles, the app's genkey validator
accepts it, and every pressure and temperature stays inside the bundled air-water
table. Toolkit topologies outside that table are classified and left out.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from . import case_compiler, case_spec, config, starter_fluids, workspace
from .genkey_static import ALLOWED_TOPOLOGIES, OlgaInputError, create_preview, review_file

_LOCK = threading.Lock()
_STEM = re.compile(r"[A-Za-z0-9_-]{1,48}")
_EXAMPLE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_TABLE_FILE = re.compile(r"air_water(?:_[0-9]+)?\.tab")
_PRESSURE = re.compile(r"PRESSURE\s*=\s*([0-9eE.+-]+)")
_TEMPERATURE = re.compile(r"TEMPERATURE\s*=\s*([0-9eE.+-]+)")
_FLUID_ONE = re.compile(r"FLUID\s*=\s*1\b")
_ADMITTED: dict[str, bool] = {}
_TOPOLOGY_CLASS: dict[str, str] = {}
_TABLE_STEM = "air_water"


class ExampleError(OlgaInputError):
    """The requested example cannot be installed."""


def _resources_dir() -> Path:
    return config.toolkit_dir().parent


def _catalog_path() -> Path:
    return _resources_dir() / "examples" / "catalog.json"


def _load_catalog() -> list[dict[str, Any]]:
    payload = json.loads(_catalog_path().read_text(encoding="utf-8"))
    rows = payload.get("examples")
    if not isinstance(rows, list):
        raise ExampleError("Example catalog is unreadable.")
    return [row for row in rows if isinstance(row, dict)]


def _pressure_bounds_pa() -> tuple[float, float]:
    low, high = starter_fluids.PRESSURE_RANGE_BAR
    return low * 1e5, high * 1e5


def _temperature_bounds() -> tuple[float, float]:
    low, high = starter_fluids.TEMPERATURE_RANGE_C
    return float(low), float(high)


def _in_table(pressure_pa: float, temperature_c: float) -> bool:
    low_pa, high_pa = _pressure_bounds_pa()
    low_c, high_c = _temperature_bounds()
    return low_pa <= pressure_pa <= high_pa and low_c <= temperature_c <= high_c


def _text_in_table(text: str) -> bool:
    pressures = [float(item) for item in _PRESSURE.findall(text)]
    temperatures = [float(item) for item in _TEMPERATURE.findall(text)]
    if not pressures or not temperatures:
        return False
    low_pa, high_pa = _pressure_bounds_pa()
    low_c, high_c = _temperature_bounds()
    return all(low_pa <= value <= high_pa for value in pressures) and all(
        low_c <= value <= high_c for value in temperatures
    )


def _spec_in_table(raw: dict[str, Any]) -> bool:
    points: list[tuple[float, float]] = []
    for node in raw.get("nodes", []):
        if isinstance(node, dict) and "pressure_pa" in node and "temperature_c" in node:
            points.append((float(node["pressure_pa"]), float(node["temperature_c"])))
    for source in raw.get("massflow_sources", []):
        if isinstance(source, dict) and "temperature_c" in source:
            points.append(((_pressure_bounds_pa()[0] + _pressure_bounds_pa()[1]) / 2, float(source["temperature_c"])))
    return bool(points) and all(_in_table(pressure, temperature) for pressure, temperature in points)


def _rewrite_fluid(text: str) -> str:
    return _FLUID_ONE.sub(f'FLUID="{starter_fluids.LABEL}"', text)


def _review_text(text: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="olga-example-") as directory:
        path = Path(directory) / "candidate.genkey"
        path.write_text(text, encoding="utf-8", newline="\n")
        return bool(review_file(str(path))["valid"])


def classify_topology(topology: str) -> str:
    """Why a toolkit topology is shown or hidden. Cached for the process."""
    cached = _TOPOLOGY_CLASS.get(topology)
    if cached is not None:
        return cached
    if topology not in ALLOWED_TOPOLOGIES:
        reason = "unknown"
    else:
        preview = create_preview(topology, endtime_s=3600, pvtfile=f"{_TABLE_STEM}.tab")
        text = _rewrite_fluid(str(preview.get("preview") or ""))
        if not preview.get("ok") or not text.strip():
            reason = "validator"
        elif not _text_in_table(text):
            reason = "out_of_table_range"
        elif not _review_text(text):
            reason = "validator"
        else:
            reason = "admitted"
    _TOPOLOGY_CLASS[topology] = reason
    return reason


def _load_spec(entry: dict[str, Any]) -> dict[str, Any]:
    spec_rel = str(entry.get("spec") or "")
    path = (_resources_dir() / spec_rel).resolve()
    if _resources_dir().resolve() not in path.parents or path.suffix != ".json":
        raise ExampleError("Example spec is not a bundled JSON file.")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ExampleError("Example spec is not an object.")
    return loaded


def _case_spec_text(entry: dict[str, Any], table_rel: str) -> str:
    raw = _load_spec(entry)
    raw["pvt_reference"] = table_rel
    result = case_spec.validate_case_spec(raw)
    if result["valid"] is not True or result["publishable"] is not True or not _spec_in_table(raw):
        raise ExampleError("Example case spec did not validate.")
    compiled = case_compiler.compile_case_spec(raw)
    if not compiled.validation.clean:
        raise ExampleError("Example case spec did not compile.")
    return compiled.text


def _topology_text(entry: dict[str, Any], table_rel: str) -> str:
    topology = str(entry.get("topology") or "")
    if classify_topology(topology) != "admitted":
        raise ExampleError("Example topology is not available.")
    preview = create_preview(topology, endtime_s=3600, pvtfile=table_rel)
    text = _rewrite_fluid(str(preview.get("preview") or ""))
    if not preview.get("ok") or not _text_in_table(text) or not _review_text(text):
        raise ExampleError("Example topology did not validate.")
    return text


def _admitted(entry: dict[str, Any]) -> bool:
    example_id = str(entry.get("id") or "")
    cached = _ADMITTED.get(example_id)
    if cached is not None:
        return cached
    try:
        if entry.get("kind") == "case_spec":
            text = _case_spec_text(entry, f"{_TABLE_STEM}.tab")
            ok = _review_text(text) and _text_in_table(text)
        elif entry.get("kind") == "topology":
            ok = classify_topology(str(entry.get("topology") or "")) == "admitted"
        else:
            ok = False
    except OSError:
        return False
    except (ExampleError, ValueError, KeyError, TypeError):
        ok = False
    _ADMITTED[example_id] = ok
    return ok


def _public(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "demo": entry.get("demo") is True,
        "topology": entry.get("topology"),
        "fluid": entry.get("fluid"),
        "title_ko": entry.get("title_ko"),
        "title_en": entry.get("title_en"),
        "description_ko": entry.get("description_ko"),
        "description_en": entry.get("description_en"),
    }


def list_examples() -> list[dict[str, Any]]:
    """Gallery rows. A row that fails admission is omitted, not shown as broken."""
    return [_public(entry) for entry in _load_catalog() if _admitted(entry)]


def _require(example_id: str) -> dict[str, Any]:
    if not _EXAMPLE_ID.fullmatch(example_id):
        raise ExampleError("Unknown example.")
    for entry in _load_catalog():
        if entry.get("id") == example_id and _admitted(entry):
            return entry
    raise ExampleError("Unknown example.")


def _place(root: Path, stem: str, suffix: str, payload: bytes) -> str:
    if not _STEM.fullmatch(stem) or suffix not in {".tab", ".genkey"}:
        raise ExampleError("Example file name is not safe.")
    for number in range(1, 1000):
        name = f"{stem}{suffix}" if number == 1 else f"{stem}_{number}{suffix}"
        path = root / name
        if path.is_symlink():
            continue
        try:
            descriptor = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o644,
            )
        except FileExistsError:
            continue
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        except Exception:
            os.close(descriptor)
            path.unlink(missing_ok=True)
            raise
        os.close(descriptor)
        return name
    raise ExampleError("No free file name left in the workspace.")


def _reusable_table(root: Path, payload: bytes) -> str | None:
    try:
        entries = list(root.iterdir())
    except OSError:
        return None
    matches: list[str] = []
    for path in entries:
        if not _TABLE_FILE.fullmatch(path.name) or path.is_symlink() or not path.is_file():
            continue
        try:
            same = path.read_bytes() == payload
        except OSError:
            continue
        if same:
            matches.append(path.name)
    if not matches:
        return None
    matches.sort(key=lambda name: (name != f"{_TABLE_STEM}.tab", name))
    return matches[0]


def install_example(example_id: str) -> dict[str, Any]:
    """Copy the bundled table and a ready genkey, then make that case active.

    An identical air-water table already in the workspace is reused. Other
    existing files keep their bytes. A validator failure deletes only the
    files this call created.
    """
    try:
        return _install_example(example_id)
    except ExampleError:
        raise
    except OSError:
        raise ExampleError("The workspace folder is not writable.") from None


def _install_example(example_id: str) -> dict[str, Any]:
    entry = _require(example_id)
    bundled = starter_fluids.bundled_table()
    if not bundled.is_file():
        raise ExampleError("The bundled air-water table is missing.")
    table_bytes = bundled.read_bytes()
    root = config.workspace_root()
    written: list[Path] = []
    with _LOCK:
        try:
            table_rel = _reusable_table(root, table_bytes)
            if table_rel is None:
                table_rel = _place(root, _TABLE_STEM, ".tab", table_bytes)
                written.append(root / table_rel)
            if entry.get("kind") == "case_spec":
                text = _case_spec_text(entry, table_rel)
            else:
                text = _topology_text(entry, table_rel)
            case_rel = _place(root, str(entry["stem"]), ".genkey", text.encode("utf-8"))
            written.append(root / case_rel)
            reviewed = review_file(str(root / case_rel))
            if reviewed["valid"] is not True:
                raise ExampleError("Installed example failed the validator.")
            active = workspace.set_active_rel(case_rel)
        except Exception:
            for path in written:
                path.unlink(missing_ok=True)
            raise
    return {
        **_public(entry),
        "case_rel": case_rel,
        "case_name": Path(case_rel).name,
        "table_rel": table_rel,
        "active": active,
        "next": "validate",
    }
