"""CaseSpec v3 PID control loop: a transmitter on one pipe section drives one valve (0.1.21).

The compiled syntax is the one OLGA 2022.1.0 ran to a normal stop with the controller moving the valve
(see the 0.1.21 G1 probe): MEASRD is an unindexed terminal, OUTSIG_1 and CONTR_1 are indexed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from olga_companion import case_compiler, case_spec
from olga_companion.case_spec_recovery import recover_case_spec

FIXTURE = Path(__file__).parent / "fixtures" / "casespec_valve.json"

LOOP = {
    "kind": "pid",
    "label": "PC_A",
    "valve": "VALVE_A",
    "measure": {"variable": "PT", "flowpath": "MAIN", "pipe": "PIPE_A", "section": 3},
    "setpoint": 1500000.0,
    "gain": -0.5,
    "integral_s": 60.0,
    "derivative_s": 0.0,
    "bias": 1.0,
    "norm_range": 100000.0,
    "stroke_s": 10.0,
}

TRANSMITTER_LINE = ' TRANSMITTER LABEL="TM_PC_A", PIPE=PIPE_A, SECTION=3, VARIABLE=PT'
CONTROLLER_BLOCK = "\n".join([
    "NETWORKCOMPONENT TYPE=PIDCONTROLLER, TAG=PC_A",
    ' PARAMETERS LABEL="PC_A", TIME=(0) s, MODE=(AUTOMATIC), SETPOINT=(1500000), '
    "AMPLIFICATION=(-0.5), INTEGRALCONST=(60) s, DERIVATIVECONST=(0) s, BIAS=1, "
    "NORMRANGE=100000, STROKETIME=10 s, MAXSIGNAL=1, MINSIGNAL=0",
    " TRENDDATA VARIABLE=(CONTR)",
    "ENDNETWORKCOMPONENT",
])
CONNECTIONS = [
    "CONNECTION TERMINALS = (MAIN TM_PC_A@OUTSIG_1, PC_A MEASRD)",
    "CONNECTION TERMINALS = (PC_A CONTR_1, MAIN VALVE_A@VALVESIG)",
]


def _spec(**loop_changes) -> dict:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["version"] = "3"
    loop = copy.deepcopy(LOOP)
    loop.update(loop_changes)
    raw["controllers"] = [loop]
    return raw


def test_a_pid_loop_compiles_in_the_syntax_olga_ran() -> None:
    compiled = case_compiler.compile_case_spec(_spec())

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    text = compiled.text
    assert TRANSMITTER_LINE in text
    assert CONTROLLER_BLOCK in text
    for line in CONNECTIONS:
        assert line in text
    # The controller drives the valve; its own opening stays as the value before the loop takes over.
    assert 'VALVE LABEL="VALVE_A"' in text
    assert text.index(CONTROLLER_BLOCK) < text.index(CONNECTIONS[0]) < text.index("ENDCASE")


def test_a_flow_loop_measures_total_mass_flow() -> None:
    measure = {"variable": "GT", "flowpath": "MAIN", "pipe": "PIPE_A", "section": 8}
    text = case_compiler.compile_case_spec(_spec(measure=measure, setpoint=2.5, norm_range=1.0)).text

    assert ' TRANSMITTER LABEL="TM_PC_A", PIPE=PIPE_A, SECTION=8, VARIABLE=GT' in text
    assert "SETPOINT=(2.5)" in text


def test_no_loops_compile_byte_identical_to_a_case_without_the_field() -> None:
    with_empty = _spec()
    with_empty["controllers"] = []
    without = _spec()
    del without["controllers"]

    assert case_compiler.render_case_spec(with_empty) == case_compiler.render_case_spec(without)


def test_a_compiled_loop_reads_back_exactly(tmp_path: Path) -> None:
    raw = _spec()
    path = tmp_path / "loop.genkey"
    path.write_bytes(case_compiler.render_case_spec(raw))

    recovered = recover_case_spec(path)

    expected = case_spec.validate_case_spec(raw)["normalized"]
    assert recovered.model_dump(mode="json", by_alias=True, exclude_none=True)["controllers"] == expected["controllers"]
    assert case_compiler.render_case_spec(recovered) == path.read_bytes()


def _refused(raw: dict) -> str:
    result = case_spec.validate_case_spec(raw)
    assert result["valid"] is False, "expected a refusal"
    return result["errors"][0]["code"]


def test_a_loop_needs_version_3() -> None:
    raw = _spec()
    raw["version"] = "2"
    assert _refused(raw) == "unsupported_controller"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"valve": "NO_SUCH_VALVE"}, "unknown_reference"),
        ({"measure": {"variable": "PT", "flowpath": "MAIN", "pipe": "NO_PIPE", "section": 3}}, "unknown_reference"),
        ({"measure": {"variable": "PT", "flowpath": "NOPE", "pipe": "PIPE_A", "section": 3}}, "unknown_reference"),
        ({"measure": {"variable": "PT", "flowpath": "MAIN", "pipe": "PIPE_A", "section": 11}}, "invalid_geometry"),
        ({"label": "VALVE_A"}, "duplicate_label"),
        ({"label": "PIPE_A"}, "duplicate_label"),
    ],
)
def test_a_loop_that_names_something_missing_or_taken_is_refused(changes: dict, code: str) -> None:
    assert _refused(_spec(**changes)) == code


@pytest.mark.parametrize(
    "changes",
    [
        {"integral_s": 0.0},
        {"integral_s": 1e-9},  # OLGA wants INTEGRALCONST above 1e-9 s
        {"derivative_s": -1.0},
        {"bias": 1.5},
        {"norm_range": 0.0},
        {"gain": 0.0},
        {"stroke_s": -1.0},
        {"setpoint": 0.0},  # a pressure setpoint must be above zero
        {"setpoint": float("nan")},
        {"measure": {"variable": "TM", "flowpath": "MAIN", "pipe": "PIPE_A", "section": 3}},
        {"label": "P" * 62},  # TM_ + label must stay a valid 64-character OLGA label
    ],
)
def test_out_of_range_loop_values_are_refused(changes: dict) -> None:
    result = case_spec.validate_case_spec(_spec(**changes))
    assert result["valid"] is False


def test_a_loop_refuses_extra_fields() -> None:
    raw = _spec()
    raw["controllers"][0]["mode"] = "MANUAL"
    assert case_spec.validate_case_spec(raw)["valid"] is False


def test_one_valve_takes_one_loop() -> None:
    raw = _spec()
    second = copy.deepcopy(LOOP)
    second["label"] = "PC_B"
    raw["controllers"].append(second)
    assert _refused(raw) == "duplicate_controller_valve"


def test_a_scheduled_valve_cannot_also_have_a_loop() -> None:
    raw = _spec()
    raw["equipment"][0]["schedule"] = [{"time_s": 0.0, "opening": 1.0}, {"time_s": 60.0, "opening": 0.5}]
    assert _refused(raw) == "controlled_valve_schedule"


def test_the_case_checker_still_flags_a_connection_to_an_undefined_controller() -> None:
    text = case_compiler.render_case_spec(_spec()).decode()
    broken = text.replace("(PC_A CONTR_1, MAIN VALVE_A@VALVESIG)", "(PC_X CONTR_1, MAIN VALVE_A@VALVESIG)")

    verification = case_compiler.verify_with_toolkit(broken)

    assert verification.validator_clean is False
    assert "PC_X" in "\n".join(verification.diagnostics)


def test_a_case_without_loops_keeps_the_hash_it_had_before_loops_existed() -> None:
    import hashlib

    from olga_companion.case_transactions import case_spec_hash

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    spec = case_spec.normalize_case_spec(raw)
    # What 0.1.20 hashed: the same dump without the field (and without an absent initial_conditions).
    before = spec.model_dump_json(by_alias=True, exclude={"initial_conditions", "controllers"}).encode("utf-8")
    assert case_spec_hash(spec) == hashlib.sha256(before).hexdigest()
    assert case_spec_hash(_spec()) != case_spec_hash(spec)
