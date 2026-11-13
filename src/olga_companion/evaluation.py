from __future__ import annotations

import json
import math
from typing import Any

from pathlib import Path

from .config import toolkit_dir
from .fluids import require_fluid_path
from .genkey_static import OlgaInputError, file_sha256, require_genkey_path, run_tool
from . import results as results_module
from .results import NAME_TOKEN
from . import workspace as workspace_module


def _criterion_file(value: Any, suffixes: set[str]) -> Path:
    """A run:/workspace: result id resolves like every other result tool; a path stays a path."""
    raw = str(value or "").strip()
    if raw.startswith(("run:", "workspace:")):
        raw = str(workspace_module.resolve_result(raw))
    return require_fluid_path(raw, suffixes)

EVAL_SCRIPTS = {
    "criterion_evaluator": "criterion_evaluator.py",
    "slug_analyzer": "slug_analyzer.py",
    "wax_hydrate_checker": "wax_hydrate_checker.py",
    "pipe_mapper": "pipe_mapper.py",
}

# Every judgement must carry this full citation set; anything less is an
# internal schema error, never a silently thinner answer.
CITATION_FIELDS = {
    "criterion",
    "verdict",
    "source_file",
    "source_sha256",
    "source_mutated",
    "variables",
    "timestep",
    "mapping",
    "formula",
    "threshold",
    "command",
}


class EvaluationSchemaError(RuntimeError):
    """A judgement was produced without its full citation set."""


def evaluation_toolkit_status() -> dict[str, Any]:
    root = toolkit_dir()
    scripts = {name: (root / "scripts" / script).exists() for name, script in EVAL_SCRIPTS.items()}
    return {
        "toolkit_dir": str(root),
        "available": root.exists() and all(scripts.values()),
        "scripts": scripts,
    }


def _token(params: dict[str, Any], key: str) -> str:
    value = str(params.get(key, "")).strip()
    if not value or not NAME_TOKEN.fullmatch(value) or value.startswith("-"):
        raise OlgaInputError(f"Invalid or missing {key!r}: {value!r}")
    return value


def _number(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise OlgaInputError(f"A numeric {key!r} is required.")
    return float(value)


def _json_or_fail(command: Any, what: str) -> dict[str, Any]:
    # The toolkit scripts print progress lines before the JSON payload and use
    # a nonzero exit code to signal a FAIL verdict (not an error), so the
    # parsed JSON — not the exit code — decides whether the run is usable.
    stdout = command.stdout
    start = stdout.find("{")
    parsed = None
    if start >= 0:
        try:
            parsed = json.loads(stdout[start:])
        except json.JSONDecodeError:
            parsed = None
    if not isinstance(parsed, dict):
        streams = (command.stderr.strip() or command.stdout.strip()).splitlines()
        detail = streams[-1] if streams else "no parseable output"
        raise OlgaInputError(f"{what} failed: {detail}")
    return parsed


def _judge_liqc(params: dict[str, Any]) -> list[dict[str, Any]]:
    ppl = _criterion_file(params.get("ppl"), {".ppl"})
    genkey = require_genkey_path(str(params.get("genkey", "")))
    flowpath = _token(params, "flowpath")
    pipe = _token(params, "pipe")
    max_litres = _number(params, "max_litres")
    args = [str(ppl), str(genkey), flowpath, pipe, str(max_litres)]
    branch = None
    if params.get("branch"):
        branch = _token(params, "branch")
        args.extend(["--branch", branch])
    if params.get("timestep") is not None:
        args.extend(["--timestep", str(_number(params, "timestep"))])
    args.append("--json")
    before = file_sha256(ppl)
    command = run_tool("criterion_evaluator", args, timeout_s=120, names=EVAL_SCRIPTS)
    parsed = _json_or_fail(command, "LIQC criterion evaluation")
    return [
        {
            "criterion": "liqc_max",
            "verdict": parsed.get("verdict"),
            "source_file": str(ppl),
            "source_sha256": before,
            "source_mutated": before != file_sha256(ppl),
            "variables": ["HOL"],
            "timestep": parsed.get("timestep"),
            "mapping": {
                "genkey": str(genkey),
                "flowpath": flowpath,
                "pipe": parsed.get("pipe_label", pipe),
                "branch": branch or "auto-detected",
                "pipe_volume_litres": parsed.get("pipe_volume_litres"),
            },
            "formula": "LIQC(pipe) = sum(HOL_section * section_volume); PASS iff LIQC <= max_litres",
            "threshold": {"max_litres": max_litres},
            "measured": {
                "liqc_litres": parsed.get("liqc_litres"),
                "ratio": parsed.get("ratio"),
                "fill_fraction": parsed.get("fill_fraction"),
            },
            "command": command.to_dict(),
        }
    ]


def _judge_slugging(params: dict[str, Any]) -> list[dict[str, Any]]:
    ppl = _criterion_file(params.get("ppl"), {".ppl"})
    branch = _token(params, "branch")
    max_slug_count = _number(params, "max_slug_count")
    before = file_sha256(ppl)
    command = run_tool(
        "slug_analyzer",
        [str(ppl), "--branch", branch, "--detect-slugs", "--json"],
        timeout_s=120,
        names=EVAL_SCRIPTS,
    )
    parsed = _json_or_fail(command, "Slug analysis")
    stats = parsed.get("slug_stats") or {}
    count = stats.get("slug_count_total", len(parsed.get("slugs_last_timestep") or []))
    return [
        {
            "criterion": "slugging_indicators",
            "verdict": "PASS" if count <= max_slug_count else "FAIL",
            "source_file": str(ppl),
            "source_sha256": before,
            "source_mutated": before != file_sha256(ppl),
            "variables": ["HOL"],
            "timestep": "all",
            "mapping": {"branch": branch},
            "formula": "HOL-based slug detection; PASS iff slug_count_total <= max_slug_count",
            "threshold": {"max_slug_count": max_slug_count},
            "measured": {"slug_count_total": count, "slug_stats": stats},
            "command": command.to_dict(),
        }
    ]


def _judge_wax_hydrate(params: dict[str, Any]) -> list[dict[str, Any]]:
    source = _criterion_file(params.get("file"), {".tpl", ".ppl"})
    branch = _token(params, "branch")
    hydrate_temp = _number(params, "hydrate_temp")
    wax_temp = _number(params, "wax_temp")
    before = file_sha256(source)
    command = run_tool(
        "wax_hydrate_checker",
        [str(source), "--branch", branch, "--hydrate-temp", str(hydrate_temp), "--wax-temp", str(wax_temp), "--json"],
        timeout_s=120,
        names=EVAL_SCRIPTS,
    )
    parsed = _json_or_fail(command, "Wax/hydrate risk check")
    mutated = before != file_sha256(source)
    judgements = []
    for criterion, threshold_key, threshold in (
        ("hydrate_risk", "hydrate_temp", hydrate_temp),
        ("wax_risk", "wax_temp", wax_temp),
    ):
        risk = parsed.get(criterion) or {}
        pct = risk.get("pct_at_risk")
        if pct is None:
            raise OlgaInputError(f"Wax/hydrate output missing {criterion}.pct_at_risk")
        judgements.append(
            {
                "criterion": criterion,
                "verdict": "PASS" if pct == 0.0 else "FAIL",
                "source_file": str(source),
                "source_sha256": before,
                "source_mutated": mutated,
                "variables": ["TM"],
                "timestep": "all",
                "mapping": {"branch": branch},
                "formula": f"subcooling = TM - {threshold_key}; PASS iff pct_at_risk == 0",
                "threshold": {threshold_key: threshold},
                "measured": risk,
                "command": command.to_dict(),
            }
        )
    return judgements


def _judge_pressure_drop(params: dict[str, Any]) -> list[dict[str, Any]]:
    """End-of-run and max-over-time pressure drop between two PT series.

    Missing inputs never produce a verdict: they come back as an
    ``input_required`` entry the caller surfaces without judging.
    """
    tpl_raw = str(params.get("tpl", "")).strip()
    inlet_position = str(params.get("inlet_position", "")).strip()
    outlet_position = str(params.get("outlet_position", "")).strip()
    unit = params.get("unit")
    unit_text = str(unit).strip() if unit is not None else ""
    missing = [
        name
        for name, present in (
            ("tpl", bool(tpl_raw)),
            ("inlet_position", bool(inlet_position)),
            ("outlet_position", bool(outlet_position)),
            ("max_drop", params.get("max_drop") is not None),
            ("unit", bool(unit_text)),
        )
        if not present
    ]
    if missing:
        return [
            {
                "criterion": "pressure_drop",
                "status": "input_required",
                "missing": sorted(missing),
            }
        ]
    max_drop = params.get("max_drop")
    if not isinstance(max_drop, (int, float)) or isinstance(max_drop, bool):
        raise OlgaInputError("A numeric max_drop is required.")
    max_drop = float(max_drop)
    if not math.isfinite(max_drop):
        raise OlgaInputError("max_drop must be finite.")
    view = {"value_unit": unit_text}
    source = results_module.resolve_result(tpl_raw)
    before = file_sha256(Path(source))
    inlet = results_module.variable_series(tpl_raw, "PT", position=inlet_position, **view)
    outlet = results_module.variable_series(tpl_raw, "PT", position=outlet_position, **view)
    inlet_times = inlet.get("time") or []
    outlet_times = outlet.get("time") or []
    inlet_values = inlet.get("values") or []
    outlet_values = outlet.get("values") or []
    if (
        not isinstance(inlet_times, list)
        or not isinstance(outlet_times, list)
        or inlet_times != outlet_times
        or len(inlet_values) != len(inlet_times)
        or len(outlet_values) != len(outlet_times)
    ):
        raise OlgaInputError("Inlet and outlet PT series have different time grids.")
    try:
        drops = [float(a) - float(b) for a, b in zip(inlet_values, outlet_values, strict=True)]
    except (TypeError, ValueError) as exc:
        raise OlgaInputError("PT series contain a non-finite value.") from exc
    if not drops or any(not math.isfinite(item) for item in (*inlet_times, *drops)):
        raise OlgaInputError("PT series contain a non-finite value.")
    drop_end = drops[-1]
    drop_max = max(drops)
    end_time = inlet_times[-1]
    time_unit = inlet.get("time_unit")
    drop_unit = unit_text or inlet.get("unit")
    return [
        {
            "criterion": "pressure_drop",
            "verdict": "PASS" if drop_max <= max_drop else "FAIL",
            "source_file": str(inlet["path"]),
            "source_sha256": before,
            "source_mutated": before != file_sha256(Path(inlet["path"])),
            "variables": ["PT"],
            "timestep": "all",
            "mapping": {
                "inlet_position": inlet.get("position"),
                "outlet_position": outlet.get("position"),
            },
            "formula": "drop(t) = PT_inlet(t) - PT_outlet(t); PASS iff max(drop) <= max_drop",
            "threshold": {"max_drop": max_drop, **({"unit": unit_text} if unit_text else {})},
            "measured": {
                "drop_end": drop_end,
                "drop_max": drop_max,
                "drop_unit": drop_unit,
                "end_time": end_time,
                "time_unit": time_unit,
            },
            "command": {
                "tool": "evaluation.pressure_drop",
                "inlet": inlet.get("position"),
                "outlet": outlet.get("position"),
            },
        }
    ]


_JUDGES = {
    "liqc": _judge_liqc,
    "slugging": _judge_slugging,
    "wax_hydrate": _judge_wax_hydrate,
    "pressure_drop": _judge_pressure_drop,
}


def _validate_judgement(judgement: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in CITATION_FIELDS if judgement.get(field) is None]
    if missing:
        raise EvaluationSchemaError(f"Judgement missing citation fields: {', '.join(sorted(missing))}")
    extras = set(judgement) - CITATION_FIELDS - {"measured"}
    if extras:
        raise EvaluationSchemaError(f"Judgement carries undeclared fields: {', '.join(sorted(extras))}")
    return judgement


def evaluate(criteria: list[dict[str, Any]]) -> dict[str, Any]:
    if not criteria:
        raise OlgaInputError("At least one criterion is required.")
    judgements: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for entry in criteria:
        kind = str(entry.get("kind", "")).strip()
        judge = _JUDGES.get(kind)
        if judge is None:
            raise OlgaInputError(f"Unknown criterion kind: {kind!r}. Choose one of: {', '.join(sorted(_JUDGES))}")
        params = entry.get("params") or {}
        if not isinstance(params, dict):
            raise OlgaInputError("criterion params must be an object.")
        for judgement in judge(params):
            if judgement.get("status") == "input_required":
                pending.append(judgement)
            else:
                judgements.append(_validate_judgement(judgement))
    return {"judgements": judgements, "pending": pending, "count": len(judgements)}
