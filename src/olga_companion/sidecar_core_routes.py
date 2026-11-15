from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException

from .sidecar_contracts import (
    CompareRequest,
    CreateRequest,
    EvaluateRequest,
    ExampleInstallRequest,
    FigureRequest,
    FindingsReportRequest,
    FlowpathDetailsRequest,
    FluidDraftRequest,
    FluidOpenRequest,
    FluidPathRequest,
    FluidPickupRequest,
    GenkeyTopologyRequest,
    MarkdownReportRequest,
    ModifyCopyRequest,
    OpcReadRequest,
    OpcWriteRequest,
    ReviewRequest,
)


router = APIRouter()


def _facade() -> Any:
    from . import sidecar

    return sidecar


@router.get("/health")
def health() -> dict[str, Any]:
    sidecar = _facade()
    return {
        "app": sidecar.APP_NAME,
        "version": sidecar.__version__,
        "frontend_port": sidecar._runtime_port(
            "OLGA_FRONTEND_PORT",
            sidecar.FRONTEND_PORT,
        ),
        "sidecar_port": sidecar._runtime_port(
            "OLGA_SIDECAR_PORT",
            sidecar.SIDECAR_PORT,
        ),
        "toolkit": sidecar.toolkit_status(),
        "capabilities": sidecar._all_capabilities(),
    }


@router.get("/api/glossary")
def api_glossary(term: str | None = None) -> dict[str, Any]:
    from .glossary import lookup

    return lookup(term)


@router.get("/api/capabilities")
def api_capabilities() -> dict[str, Any]:
    return _facade()._all_capabilities()


@router.get("/api/genkey/topologies")
def topologies() -> dict[str, list[str]]:
    return {"topologies": sorted(_facade().ALLOWED_TOPOLOGIES)}


@router.get("/api/examples")
def api_examples() -> dict[str, Any]:
    from .examples import list_examples

    return {"examples": list_examples()}


@router.post("/api/examples/install")
def api_examples_install(
    request: ExampleInstallRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    from .examples import install_example

    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    return sidecar._handle(lambda: install_example(request.id))


@router.post("/api/genkey/create")
def api_create(request: CreateRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.create_preview(
            request.topology,
            request.endtime_s,
            request.pvtfile,
        )
    )


@router.post("/api/genkey/review")
def api_review(request: ReviewRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.review_file(sidecar._input_file(request.path, {".genkey"}))
    )


@router.post("/api/genkey/topology")
def api_genkey_topology(request: GenkeyTopologyRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.parse_network(sidecar._input_file(request.rel, {".genkey"}))
    )


@router.post("/api/genkey/flowpath-details")
def api_flowpath_details(request: FlowpathDetailsRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.load_flowpath_details(
            sidecar._workspace_file(request.rel, {".genkey"}),
            request.flowpath,
        )
    )


@router.post("/api/genkey/modify-copy")
def api_modify_copy(request: ModifyCopyRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.modify_copy(
            sidecar._input_file(request.source, {".genkey"}),
            request.keyword,
            request.key,
            request.value,
            request.label,
        )
    )


@router.post("/api/fluids/inspect-tab")
def api_inspect_tab(request: FluidPathRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.inspect_tab(sidecar._input_file(request.path, {".tab"}))
    )


@router.post("/api/fluids/inspect-mfl")
def api_inspect_mfl(request: FluidPathRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.inspect_mfl(sidecar._input_file(request.path, {".mfl"}))
    )


@router.post("/api/fluids/consistency")
def api_fluids_consistency(request: FluidPathRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.consistency(sidecar._input_file(request.path, {".genkey"}))
    )


@router.post("/api/fluids/draft-preview")
def api_fluids_draft_preview(request: FluidDraftRequest) -> dict[str, Any]:
    from . import fluid_table
    from . import workspace as _workspace

    try:
        label = fluid_table.validate_label(request.fluid_label)
        model = fluid_table.validate_model(request.model)
        names = fluid_table.databank_names()
        components = fluid_table.validate_composition(
            fluid_table.spell_components(
                [item.model_dump() for item in request.components], names,
            ),
            names,
        )
        temperatures = fluid_table.validate_grid(list(request.temperatures), "temperature")
        pressures = fluid_table.validate_grid(list(request.pressures), "pressure")
        target = _workspace.contained(request.mfl_rel)
        if target.suffix.casefold() != ".mfl":
            raise fluid_table.FluidTableError("Draft destination must end in .mfl.")
        tab_target = (
            _workspace.contained(request.tab_rel)
            if request.tab_rel
            else target.with_suffix(".tab")
        )
        tab_abs = str(tab_target.resolve())
        command = fluid_table.build_table_command(
            tab_abs, label, temperatures, request.temperature_unit,
            pressures, request.pressure_unit, hawater=request.hawater,
        )
        text = fluid_table.build_mfl_text(
            fluid_label=label, components=components, model=model,
            temperatures=temperatures, temperature_unit=request.temperature_unit,
            pressures=pressures, pressure_unit=request.pressure_unit,
            tab_abs_path=tab_abs, hawater=request.hawater,
        )
    except (fluid_table.FluidTableError, _workspace.WorkspaceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "mfl_rel": request.mfl_rel,
        "tab_abs": tab_abs,
        "table_command": command,
        "mfl_text": text,
        "writes_nothing": True,
    }


@router.post("/api/fluids/open-multiflash")
def api_fluids_open_multiflash(request: FluidOpenRequest) -> dict[str, Any]:
    from . import fluid_table

    if not request.approved:
        raise HTTPException(
            status_code=400,
            detail="Opening Multiflash requires explicit per-request approval (approved=true).",
        )
    sidecar = _facade()
    mfl_path: str | None = None
    if request.mfl_path:
        try:
            mfl_path = sidecar._input_file(request.mfl_path, {".mfl"})
        except (sidecar.OlgaInputError, sidecar.workspace.WorkspaceError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    discovery = fluid_table.find_multiflash()
    if not discovery["found"]:
        raise HTTPException(status_code=404, detail=discovery["message"])
    try:
        return fluid_table.launch_multiflash(discovery["exe"], mfl_path)
    except fluid_table.FluidTableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/fluids/pickup-tab")
def api_fluids_pickup_tab(request: FluidPickupRequest) -> dict[str, Any]:
    from . import fluid_table

    sidecar = _facade()
    try:
        resolved = sidecar._input_file(request.path, {".tab", ".mfl"})
    except (sidecar.OlgaInputError, sidecar.workspace.WorkspaceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tab_path = resolved
    if resolved.casefold().endswith(".mfl"):
        try:
            expected = fluid_table.expected_tab_for_mfl(resolved)
        except fluid_table.FluidTableError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if expected is None:
            raise HTTPException(
                status_code=400,
                detail="The .mfl has no table Olga .tab path to pick up.",
            )
        tab_path = expected
    try:
        return fluid_table.pickup_tab(tab_path, request.fluid_label)
    except fluid_table.FluidTableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/evaluate")
def api_evaluate(request: EvaluateRequest) -> dict[str, Any]:
    sidecar = _facade()
    try:
        return sidecar._handle(
            lambda: sidecar.evaluate(
                [criterion.model_dump() for criterion in request.criteria]
            )
        )
    except sidecar.EvaluationSchemaError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/reports/markdown")
def api_reports_markdown(request: MarkdownReportRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.markdown_report(
            sidecar._input_file(request.genkey, {".genkey"}),
            sidecar._result_file(request.results) if request.results else None,
            sidecar._result_file(request.ppl) if request.ppl else None,
            request.criterion,
            request.flowpath,
            request.pipe,
            request.title,
        )
    )


@router.post("/api/reports/findings")
def api_reports_findings(
    request: FindingsReportRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)

    def build() -> dict[str, Any]:
        report = sidecar.findings_report(
            sidecar._input_file(request.case_file, {".genkey"}),
            sidecar._result_file(request.results_file),
            request.verdicts,
            request.figures,
            request.variables,
            request.run_id,
        )
        artifact = sidecar.stage_findings_markdown(report["markdown"], report["filename"])
        return {**report, "artifact": artifact}

    return sidecar._handle(build)


@router.post("/api/reports/figure")
def api_reports_figure(request: FigureRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.generate_figure(
            request.kind,
            sidecar._result_file(request.file),
            request.branch,
            request.criterion,
            request.timestep,
        )
    )


@router.post("/api/reports/compare")
def api_reports_compare(request: CompareRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.compare_cases(
            [sidecar._result_file(path) for path in request.files],
            request.labels,
            request.variables,
            request.branch,
            request.timestep,
        )
    )


@router.get("/api/opc/status")
def api_opc_status() -> dict[str, Any]:
    return _facade().opc_gate_status()


@router.post("/api/opc/read")
def api_opc_read(request: OpcReadRequest) -> dict[str, Any]:
    sidecar = _facade()
    try:
        sidecar.require_open_gate()
    except sidecar.OpcGateClosedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise HTTPException(
        status_code=501,
        detail=(
            "OPC read is not implemented until the gate opens on a verified Windows host."
        ),
    )


@router.post("/api/opc/write")
def api_opc_write(request: OpcWriteRequest) -> dict[str, Any]:
    if not request.approved:
        raise HTTPException(
            status_code=400,
            detail="OPC writes require explicit per-request approval (approved=true).",
        )
    if not request.snapshot_id or not request.snapshot_id.strip():
        raise HTTPException(
            status_code=400,
            detail="OPC writes require a snapshot_id for rollback.",
        )
    sidecar = _facade()
    try:
        sidecar.require_open_gate()
    except sidecar.OpcGateClosedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise HTTPException(
        status_code=501,
        detail=(
            "OPC write is not implemented until the gate opens on a verified Windows host."
        ),
    )
