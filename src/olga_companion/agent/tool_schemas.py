"""Tool metadata and the single closed-schema model capability registry."""

from __future__ import annotations

from collections.abc import Mapping

from .tool_human_actions import DIRECT_HUMAN_ACTIONS
from .tool_side_effects import SIDE_EFFECT_TOOL_METADATA
from .tool_artifact_schemas import (
    ARTIFACT_RECEIPT_SCHEMA,
    NATIVE_SAVE_AS_ACTION_SCHEMA,
)
from .tool_response_catalog import TOOL_RESPONSE_SCHEMAS
from .. import config
from .tool_schema_catalog import (
    TOOL_PARAMETER_SCHEMAS,
    action_plan_schema,
    case_edit_plan_schema,
    parameter_schema,
)
from .case_transaction_schemas import DESTINATION_RULE
from .tool_schema_model import Tool, ToolHandler, schema

__all__ = ["ARTIFACT_RECEIPT_SCHEMA", "DIRECT_HUMAN_ACTIONS", "NATIVE_SAVE_AS_ACTION_SCHEMA", "build_tools"]

_PLAN_NATIVE_SENTENCE = (
    " In this build fluids_generate_tab (the in-app table generator) may also be a step; a "
    "case_publish step right after it may save a case that links the table it creates."
)


def build_tools(handlers: Mapping[str, ToolHandler], *, native_tab: bool | None = None) -> dict[str, Tool]:
    """Build the registry; the in-app table generator is registered only when ``native_tab`` is on."""
    native = config.native_tab_enabled() if native_tab is None else native_tab

    def bind(
        name: str,
        description: str,
        props: dict[str, str],
        required: list[str],
        *,
        handler_name: str | None = None,
        side_effect: bool = False,
    ) -> Tool:
        suffix = handler_name or name
        parameters = {
            "action_plan": lambda: action_plan_schema(native),
            "case_edit_plan": lambda: case_edit_plan_schema(native),
            "fluids_generate_tab": lambda: parameter_schema(name),
        }.get(name)
        return Tool(
            name,
            description,
            parameters() if parameters else TOOL_PARAMETER_SCHEMAS.get(name, schema(props, required)),
            handlers[f"_t_{suffix}"],
            side_effect,
            TOOL_RESPONSE_SCHEMAS.get(name),
        )

    def bind_side_effect(name: str) -> Tool:
        description, props, required = SIDE_EFFECT_TOOL_METADATA[name]
        if name == "action_plan" and native:
            description += _PLAN_NATIVE_SENTENCE
        if name == "fluids_generate_tab":
            from .. import native_tab

            description = description.replace("{nodes}", str(native_tab.MAX_GRID_NODES))
        return bind(name, description, props, required, side_effect=True)

    tools = [
        bind(
            "case_spec_validate",
            "Validate and normalize CaseSpec v2 or v3 JSON for a bounded arbitrary split/merge pipeline (v3 adds a stated start state: integration.steady_state false with initial_conditions); data-only, read-only, and never accepts raw GENKEY. OLGA is Y-up: centerline_m is [x, y, z] and y is elevation. Fluid label, boundary temperatures, pipe roughness and the adiabatic/ambient thermal choice are required user inputs with no defaults: ask the user, never fill them in.",
            {"spec": "object"},
            ["spec"],
        ),
        bind(
            "case_spec_compile",
            "Deterministically compile and parser/validator round-trip a valid CaseSpec v2 or v3 preview; read-only, no publish, and no owner mutation.",
            {"spec": "object", "owner_source": "string"},
            ["spec"],
        ),
        bind(
            "case_edit_plan",
            "Plan reviewed, hash-bound CaseSpec edits. " + DESTINATION_RULE,
            {},
            [],
        ),
        bind(
            "pipe_table_import",
            "Import a pipe table into a draft. "
            "Ask for pvt_reference, fluid_label, thermal, end_time_s; never fill in. "
            "layout endpoints joins coords; vertical_axis (y|z): table height column; OLGA is Y-up; never guess. "
            "On refusal ask only for the missing items listed; never invent. "
            "Near misses need a joining pipe of 0.1 m max. "
            "Returns draft_id, boundaries (no re-ask), split_rows; never rebuild.",
            {},
            [],
        ),
        bind(
            "case_draft_review",
            "Page through a draft made by pipe_table_import: counts, caps, section statistics and 50 "
            "flowpaths per page (label, source name, pipes, sections, from, to). Read-only. Never "
            "rebuild a spec by hand from a draft; use draft_id.",
            {},
            [],
        ),
        bind(
            "case_draft_edit",
            "Typed draft ops: resegment, set_valve_schedule, set_boundary, set_fluid, set_thermal, "
            "set_end_time. Pass the current revision; rebuilt or nothing changes. Private draft only. "
            "Never rebuild by hand; use draft_id.",
            {},
            [],
        ),
        bind_side_effect("case_publish"),
        bind_side_effect("action_plan"),
        bind("simulation_setup", "Preflight an exact typed simulation setup.", {}, []),
        bind("run_patrol", "Bounded single-flight restart-safe run patrol.", {}, []),
        bind(
            "genkey_create",
            "Build a preview GENKEY from a named topology template.",
            {"topology": "string", "endtime_s": "integer", "pvtfile": "string"},
            ["topology"],
        ),
        bind(
            "genkey_review",
            "Validate + summarize + draw the topology of a GENKEY case. Omit path to use the active workspace case. When the file is a compiler artifact, case_spec is the recovered CaseSpec; otherwise case_spec is null. Copy the returned source_sha256 into case_edit_plan source_hash.",
            {"path": "string"},
            [],
        ),
        bind(
            "genkey_topology",
            "Get a case's network as a {nodes, edges} graph for the interactive topology map (nodes=junctions, edges=flowpaths). Omit path to use the active case.",
            {"path": "string"},
            [],
        ),
        bind(
            "genkey_modify",
            "Set one keyword/key to a value on a sandbox copy of a case (never mutates the source). Omit path to use the active case.",
            {
                "path": "string",
                "keyword": "string",
                "key": "string",
                "value": "string",
                "label": "string",
            },
            ["keyword", "key", "value"],
        ),
        bind(
            "genkey_diff",
            "Diff two GENKEY cases — what changed between them.",
            {"path_a": "string", "path_b": "string"},
            ["path_a", "path_b"],
        ),
        bind_side_effect("genkey_save"),
        bind(
            "opi_parse",
            "Parse an OLGA .opi project file (version, components, layout).",
            {"path": "string"},
            ["path"],
        ),
        bind(
            "pipe_geometry",
            "Pipe-level geometry of a flowpath (op: list_pipes|sections|volume|elevation_profile|lowest_point). Omit path to use the active case.",
            {"path": "string", "flowpath": "string", "op": "string"},
            ["flowpath"],
        ),
        bind(
            "parametric_sweep",
            "Plan a multi-case parametric study (dry-run: generate the case matrix, no sims) and return sweep_id plus plan_id for later approval. sweep = KEYWORD.KEY=v1,v2,v3. Omit base to use the active case.",
            {
                "base": "string",
                "sweep": "string",
                "strategy": "string",
                "max_cases": "integer",
                "timeout_s": "integer",
            },
            ["sweep"],
        ),
        bind_side_effect("sweep_execute"),
        bind_side_effect("sweep_cancel"),
        bind(
            "sweep_status",
            "Poll the aggregate and per-case state of a previewed or started sweep.",
            {"sweep_id": "string"},
            ["sweep_id"],
        ),
        bind(
            "fluids_inspect_tab",
            "Parse + validate a .tab PVT table.",
            {"path": "string"},
            ["path"],
            handler_name="fluids_tab",
        ),
        bind(
            "fluids_inspect_mfl",
            "Parse a .mfl Multiflash input (components + models).",
            {"path": "string"},
            ["path"],
            handler_name="fluids_mfl",
        ),
        bind(
            "fluids_consistency",
            "Check that a GENKEY's PVTFILE references resolve. Omit path to use the active case.",
            {"path": "string"},
            [],
        ),
        bind(
            "fluids_draft_preview",
            "Preview a Multiflash .mfl draft from the user's own fluid composition (read-only, writes nothing). The composition must be user-supplied with mole fractions summing to 1; the EOS model is an explicit user choice.",
            {},
            [],
        ),
        bind(
            "fluids_pickup_tab",
            "Validate a produced .tab against its PVTTABLE LABEL and propose the normal edit + approval link. Never invents composition data.",
            {"path": "string"},
            ["path"],
        ),
        bind(
            "fluids_compare_tab",
            "Compare two .tab files for the same fluid (reference_rel, candidate_rel): per-column relative differences over the nodes they share, read-only, writes nothing.",
            {"reference_rel": "string", "candidate_rel": "string"},
            ["reference_rel", "candidate_rel"],
        ),
        bind_side_effect("fluids_draft_mfl"),
        bind_side_effect("fluids_starter_tab"),
        *([bind_side_effect("fluids_generate_tab")] if native else []),
        bind_side_effect("multiflash_open"),
        bind(
            "results_load",
            "List variables + metadata of a .tpl/.ppl result.",
            {"path": "string"},
            ["path"],
        ),
        bind(
            "results_inventory",
            "Discover bounded workspace results by opaque result identity.",
            {"offset": "integer", "limit": "integer"},
            [],
        ),
        bind(
            "results_series",
            "Read a bounded numeric series from an opaque result identity.",
            {
                "result_id": "string",
                "variable": "string",
                "position": "string",
                "value_unit": "string",
                "time_unit": "string",
                "quantity_kind": "string",
                "time_range": "object",
                "offset": "integer",
                "row_limit": "integer",
                "truncation": "string",
            },
            ["result_id", "variable"],
        ),
        bind(
            "results_profile",
            "Read one variable along a branch of a .ppl result at one time (default: the last "
            "time), as position/value rows with the maximum and minimum and where they are. "
            "change_since_previous gives the largest change from the previous saved time; if it "
            "is large the profile is still developing, so say so instead of calling it settled.",
            {"result_id": "string", "variable": "string", "branch": "string", "timestep": "number"},
            ["result_id", "variable", "branch"],
        ),
        bind(
            "results_csv",
            "Export selected variables of a result to CSV.",
            {"path": "string", "variables": "array", "branch": "string"},
            ["path", "variables"],
        ),
        bind(
            "results_plot",
            "Render a plot of selected result variables. For a .ppl profile along the pipe, give "
            "branch and one variable; timestep picks the time (default: the last).",
            {"path": "string", "variables": "array", "branch": "string"},
            ["path", "variables"],
        ),
        bind(
            "evaluate",
            "Run engineering judgements (LIQC, slugging, hydrate/wax margins).",
            {"criteria": "array"},
            ["criteria"],
        ),
        bind(
            "report_markdown",
            "Generate an auditable Markdown report with a Sources footer.",
            {"genkey": "string", "results": "string"},
            ["genkey"],
        ),
        bind(
            "report_figure",
            "Render a publication figure from a result.",
            {"kind": "string", "file": "string", "branch": "string"},
            ["kind", "file", "branch"],
        ),
        bind(
            "report_compare",
            "Compare cases/results across variables.",
            {
                "files": "array",
                "labels": "array",
                "variables": "string",
                "branch": "string",
            },
            ["files"],
        ),
        bind(
            "olga_glossary",
            "Look up one OLGA glossary term from the shipped source list. An unknown term is not guessed.",
            {"term": "string"},
            [],
        ),
        bind(
            "diagnose_out",
            "Analyze an OLGA .out solver log for convergence/mass-error issues and fixes.",
            {"path": "string"},
            ["path"],
        ),
        bind(
            "monitor_snapshot",
            "One-shot bounded solver evidence + file-activity snapshot; never process status.",
            {"path": "string"},
            ["path"],
        ),
        bind(
            "run_detect",
            "Select a suitable installed OLGA release for a case and explain the case evidence, rationale, and alternatives. Omit source to use the active case.",
            {"source": "string"},
            [],
        ),
        bind(
            "run_preview",
            "Build the exact run command for a case (no execution; for human approval). Omit source to use the active case. "
            "timeout_s is the wall-clock limit for the solver process (default 3600 s), not the simulated end time; "
            "leave it unset unless the user asks, since a run usually takes far less real time than it simulates.",
            {"source": "string", "timeout_s": "integer"},
            [],
        ),
        bind_side_effect("run_execute"),
        bind_side_effect("run_cancel"),
        bind(
            "run_status",
            "Poll the state of a started run.",
            {"run_id": "string"},
            ["run_id"],
        ),
    ]
    return {tool.name: tool for tool in tools}
