"""CaseSpec v2 trend and profile variables."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from olga_companion import case_compiler, case_spec
from olga_companion.agent.case_transaction_schemas import CASE_TRANSACTION_PARAMETER_SCHEMAS
from olga_companion.case_transaction_models import SetOutputs

FIXTURE = Path(__file__).parent / "fixtures" / "casespec_outputs.json"
ALLOWED = ("GT", "HOL", "ID", "LIQC", "PT", "QLT", "TM")


def _spec() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _output_schema() -> dict:
    operations = CASE_TRANSACTION_PARAMETER_SCHEMAS["case_edit_plan"]["properties"]["operations"]
    return operations["items"]["properties"]["outputs"]


def test_output_variables_compile_into_trend_and_profile() -> None:
    raw = _spec()

    validated = case_spec.validate_case_spec(raw)
    compiled = case_compiler.compile_case_spec(raw)

    assert validated["valid"] is True
    assert validated["normalized"]["outputs"] == list(ALLOWED)
    assert compiled.validation.clean is True, compiled.validation.diagnostics
    text = compiled.text
    output_names = ("HOL", "ID", "LIQC", "PT", "QLT", "TM")
    profile_names = ("HOL", "ID", "PT", "QLT", "TM")
    positional_names = ("GT", "HOL", "ID", "PT", "QLT", "TM")
    assert f"OUTPUTDATA VARIABLE=({', '.join(output_names)})" in text
    assert f"PROFILEDATA VARIABLE=({', '.join(profile_names)})" in text
    positional = ", ".join(positional_names)
    assert (
        f"TRENDDATA POSITION=(POS_MAIN_1, POS_MAIN), VARIABLE=({positional})"
    ) in text
    assert "TRENDDATA VARIABLE=LIQC" in text
    for name in ("HOL", "PT"):
        assert f"TRENDDATA VARIABLE={name}" not in text
    assert "PROFILEDATA" in text and "LIQC" not in next(
        line for line in text.splitlines() if "PROFILEDATA" in line
    )
    assert "GT" not in next(line for line in text.splitlines() if "OUTPUTDATA" in line)
    assert compiled.validation.outputs == output_names


@pytest.mark.parametrize("name", ["QG", "USL"])
def test_output_variables_reject_ungrounded_names(name: str) -> None:
    raw = _spec()
    raw["outputs"] = ["PT", name]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "unsupported_output"


def _lines_with(text: str, keyword: str) -> list[str]:
    return [line for line in text.splitlines() if keyword in line]


def test_liqc_is_output_and_global_trend_only() -> None:
    raw = _spec()
    raw["outputs"] = ["LIQC"]

    compiled = case_compiler.compile_case_spec(raw)
    text = compiled.text

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert "OUTPUTDATA VARIABLE=(LIQC)" in text
    assert "TRENDDATA VARIABLE=LIQC" in text
    for line in _lines_with(text, "PROFILEDATA"):
        assert "LIQC" not in line
    for line in _lines_with(text, "TRENDDATA"):
        if "POSITION" in line:
            assert "LIQC" not in line


def test_gt_is_emitted_only_on_positional_trend() -> None:
    raw = _spec()
    raw["outputs"] = ["GT"]

    compiled = case_compiler.compile_case_spec(raw)
    text = compiled.text

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert "TRENDDATA POSITION=(POS_MAIN_1, POS_MAIN), VARIABLE=(GT)" in text
    for line in text.splitlines():
        if "GT" not in line:
            continue
        assert "TRENDDATA" in line and "POSITION" in line


def test_set_outputs_op_enum_matches_the_grounded_allow_list() -> None:
    schema = _output_schema()
    operation = SetOutputs.model_validate({"op": "set_outputs", "outputs": list(ALLOWED)})

    assert schema["maxItems"] == len(ALLOWED)
    assert set(schema["items"]["enum"]) >= set(ALLOWED)
    assert "QG" not in schema["items"]["enum"]
    assert "USL" not in schema["items"]["enum"]
    assert operation.outputs == ALLOWED
