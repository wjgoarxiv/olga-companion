from pathlib import Path

from olga_companion.case_compiler_toolkit import verify_with_toolkit


def test_toolkit_normalizes_hour_endtime_to_si_seconds() -> None:
    source = Path(__file__).parent / "fixtures" / "fluids" / "case_ok.genkey"

    verified = verify_with_toolkit(source.read_text(encoding="utf-8"))

    assert verified.clean is True
    assert verified.end_time_s == 86_400.0
