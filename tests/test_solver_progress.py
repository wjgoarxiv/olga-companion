from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from olga_companion import diagnostics
from olga_companion.run_outputs import log_indicates_failure, read_log_tail, redact_log_paths


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "progress"


def test_operator_log_tail_redacts_windows_and_wsl_absolute_paths() -> None:
    text = (
        "INPUT FILE : C:\\Users\\Jordan\\Private Folder\\case.genkey\n"
        "LOG FILE : /mnt/c/Users/Jordan/Private Folder/case.out\n"
        "HOME LOG : /home/jordan/private/run.log\n"
        "FLUID PROP. FILE : demo_water_air_evap.tab"
    )

    redacted = redact_log_paths(text)

    assert "C:\\" not in redacted
    assert "/mnt/c/" not in redacted
    assert "/home/" not in redacted
    assert "INPUT FILE : case.genkey" in redacted
    assert "LOG FILE : case.out" in redacted
    assert "HOME LOG : run.log" in redacted
    assert "FLUID PROP. FILE : demo_water_air_evap.tab" in redacted


def test_vendor_progress_reads_the_hour_unit_olga_prints_past_one_hour(tmp_path: Path) -> None:
    # OLGA 2022.1 run.log of a 7200 s run: minutes up to one hour, then "H".
    out_path = tmp_path / "adaptive.out"
    log_path = tmp_path / "run.log"
    out_path.write_bytes((FIXTURE_DIR / "demo_adaptive.out").read_bytes())
    log_path.write_text(
        "Elapsed simulation-time is now:      60.00 MIN  (  50.0% of simulation completed )\n"
        "Elapsed simulation-time is now:       1.20 H    (  60.0% of simulation completed )\n"
        "Elapsed simulation-time is now:       2.00 H    ( 100.0% of simulation completed )\n",
        encoding="utf-8",
    )

    vendor, status = diagnostics._parse_vendor_progress(log_path.read_text(encoding="utf-8"))
    snapshot = diagnostics.monitor_snapshot(str(out_path), str(log_path))

    assert status == "valid"
    assert vendor["simulation_time_s"] == pytest.approx(7200.0)
    assert snapshot["vendor_percent"] == 100.0
    assert snapshot["fraction"] == 1.0


def test_adaptive_step_denominators_are_evidence_never_completion_percent(tmp_path: Path) -> None:
    out_path = tmp_path / "adaptive.out"
    out_path.write_bytes((FIXTURE_DIR / "demo_adaptive.out").read_bytes())

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert snapshot["step"] == 4210
    assert snapshot["adaptive_total_steps"] == 9910
    assert snapshot["simulation_time_s"] == 1350.0
    assert snapshot["step_size_s"] == 0.25
    assert snapshot["vendor_percent"] is None
    assert snapshot["fraction"] is None
    assert "progress" not in snapshot


def test_explicit_finite_bounded_vendor_percent_is_the_only_fraction(tmp_path: Path) -> None:
    out_path = tmp_path / "adaptive.out"
    log_path = tmp_path / "run.log"
    out_path.write_bytes((FIXTURE_DIR / "demo_adaptive.out").read_bytes())
    log_path.write_bytes((FIXTURE_DIR / "demo_run.log").read_bytes())

    snapshot = diagnostics.monitor_snapshot(str(out_path), str(log_path))

    assert snapshot["vendor_percent"] == 100.0
    assert snapshot["fraction"] == 1.0
    assert snapshot["simulation_time_s"] == 1350.0, "the .out observation remains the simulation-time evidence"
    assert snapshot["evidence"]["vendor_percent"] == "valid"


@pytest.mark.parametrize(
    "percent",
    ["NaN", "Inf", "-1", "100.0001", "not-a-number"],
)
def test_nonfinite_negative_and_out_of_range_vendor_percent_is_indeterminate(
    tmp_path: Path, percent: str
) -> None:
    log_path = tmp_path / "run.log"
    log_path.write_text(
        f"Elapsed simulation-time is now: 7.50 MIN ( {percent}% of simulation completed )\n",
        encoding="utf-8",
    )

    snapshot = diagnostics.monitor_snapshot(str(tmp_path / "missing.out"), str(log_path))

    assert snapshot["vendor_percent"] is None
    assert snapshot["fraction"] is None
    assert snapshot["parse_status"] in {"parsed", "malformed", "indeterminate"}


def test_missing_empty_truncated_and_malformed_files_return_structured_indeterminate_evidence(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty.out"
    empty.write_bytes(b"")
    truncated = tmp_path / "truncated.out"
    truncated.write_bytes(b"--*++*-- Time: 10s. Step no: 20/30. Current step-")
    malformed = tmp_path / "malformed.out"
    malformed.write_text(
        "--*++*-- Time: NaNs. Step no: 20/30. Current step-size: Infs\n",
        encoding="utf-8",
    )

    snapshots = [
        diagnostics.monitor_snapshot(str(tmp_path / "missing.out")),
        diagnostics.monitor_snapshot(str(empty)),
        diagnostics.monitor_snapshot(str(truncated)),
        diagnostics.monitor_snapshot(str(malformed)),
    ]

    assert {item["parse_status"] for item in snapshots} >= {"missing", "empty"}
    assert all(item["fraction"] is None for item in snapshots)
    assert all(item["step"] is None for item in snapshots)
    assert all(Path(item["files"]["out"]).name == item["files"]["out"] for item in snapshots)
    assert all("/" not in item["files"]["out"] and "\\" not in item["files"]["out"] for item in snapshots)


def test_permission_error_is_not_raised_or_exposed_as_an_absolute_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out_path = tmp_path / "locked.out"
    out_path.write_text("locked", encoding="utf-8")
    real_open = Path.open

    def denied(path: Path, *args, **kwargs):
        if path == out_path:
            raise PermissionError("sharing violation")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert snapshot["parse_status"] == "unreadable"
    assert snapshot["files"]["out"] == "locked.out"
    assert str(tmp_path) not in json.dumps(snapshot)


def test_tail_reads_are_byte_bounded_and_boundary_fragments_are_discarded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out_path = tmp_path / "large.out"
    padding = b"x" * (diagnostics._SNAPSHOT_TAIL_BYTES + 128)
    out_path.write_bytes(
        b"--*++*-- Time: 1s. Step no: 1/2. Current step-size: 1s\n"
        + padding
        + b"\n--*++*-- Time: 9s. Step no: 9/99. Current step-size: 0.5s\n"
    )
    real_open = Path.open
    requested_sizes: list[int] = []

    class TrackingHandle:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def fileno(self):
            return self.wrapped.fileno()

        def seek(self, *args):
            return self.wrapped.seek(*args)

        def read(self, size=-1):
            requested_sizes.append(size)
            return self.wrapped.read(size)

    def tracked(path: Path, *args, **kwargs):
        return TrackingHandle(real_open(path, *args, **kwargs))

    monkeypatch.setattr(Path, "open", tracked)

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert requested_sizes and all(0 <= size <= diagnostics._SNAPSHOT_TAIL_BYTES for size in requested_sizes)
    assert snapshot["step"] == 9
    assert snapshot["fraction"] is None


def test_out_tail_never_parses_a_timestep_manufactured_from_a_mid_line_fragment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    timestep = b"--*++*-- Time: 9s. Step no: 9/99. Current step-size: 0.5s\n"
    dangerous_line = b"X" + timestep
    out_path = tmp_path / "fragment.out"
    out_path.write_bytes(b"prefix\n" + dangerous_line + b"ordinary final line\n")
    # Start the bounded window at the timestep marker, one byte into an actual
    # line. Treating the window start as a line start would manufacture evidence.
    monkeypatch.setattr(diagnostics, "_SNAPSHOT_TAIL_BYTES", len(timestep) + len(b"ordinary final line\n"))

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert snapshot["step"] is None
    assert snapshot["fraction"] is None


def test_log_tail_discards_a_failure_marker_manufactured_from_a_mid_line_fragment(tmp_path: Path) -> None:
    dangerous_line = b"11 case(s) failed\n"
    suffix = b"ordinary final line\n"
    log_path = tmp_path / "run.log"
    log_path.write_bytes(b"prefix\n" + dangerous_line + suffix)
    # The window starts on the second "1". Without boundary-line discard this
    # becomes the anchored failure record "1 case(s) failed".
    limit = len(dangerous_line) - 1 + len(suffix)

    tail = read_log_tail(tmp_path, log_path, limit)

    assert not log_indicates_failure(tail)
    assert "ordinary final line" in tail


def test_aggregate_log_tail_never_manufactures_failure_across_source_boundary(tmp_path: Path) -> None:
    summary = "11 case(s) failed\n"
    newest = "ordinary final line\n"
    (tmp_path / "BatchExecutionSummary.txt").write_text(summary, encoding="utf-8")
    (tmp_path / "BatchExecutionSummary.txt.simOut").write_text(newest, encoding="utf-8")
    aggregate = "\n".join((summary, newest))
    limit = len(aggregate) - 1  # Current aggregate [-limit:] starts at the second "1".

    tail = read_log_tail(tmp_path, tmp_path / "run.log", limit)

    assert len(tail) <= limit
    assert tail.startswith("ordinary final line"), "bounded aggregate must start at a real line boundary"
    assert not log_indicates_failure(tail)


def test_runner_log_tail_poll_never_reads_the_entire_run_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "run.log"
    log_path.write_bytes(b"BEGIN-MUST-NOT-BE-READ\n" + b"x" * 4096 + b"\nBOUNDED-END\n")
    real_open = Path.open
    requested_sizes: list[int] = []

    class TrackingHandle:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def fileno(self):
            return self.wrapped.fileno()

        def seek(self, *args):
            return self.wrapped.seek(*args)

        def read(self, size=-1):
            requested_sizes.append(size)
            return self.wrapped.read(size)

    def tracked(path: Path, *args, **kwargs):
        return TrackingHandle(real_open(path, *args, **kwargs))

    monkeypatch.setattr(Path, "open", tracked)

    tail = read_log_tail(tmp_path, log_path, 128)

    assert requested_sizes == [128]
    assert "BOUNDED-END" in tail
    assert "BEGIN-MUST-NOT-BE-READ" not in tail


def test_implausible_adaptive_total_is_dropped(tmp_path: Path) -> None:
    out_path = tmp_path / "weird.out"
    out_path.write_text(
        "--*++*-- Time: 1.000000e+01s. Step no: 1804/4294969099. Current step-size: 2.500000e-01s\n",
        encoding="utf-8",
    )

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert snapshot["adaptive_total_steps"] is None


def test_implausible_total_keeps_the_rest_of_the_record(tmp_path: Path) -> None:
    out_path = tmp_path / "weird2.out"
    out_path.write_text(
        "--*++*-- Time: 1.000000e+01s. Step no: 1804/4294969099. Current step-size: 2.500000e-01s\n",
        encoding="utf-8",
    )

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert snapshot["step"] == 1804
    assert snapshot["simulation_time_s"] == 10.0
    assert snapshot["parse_status"] == "parsed"
    assert snapshot["adaptive_total_steps"] is None


def test_plausible_adaptive_total_is_kept(tmp_path: Path) -> None:
    out_path = tmp_path / "ok.out"
    out_path.write_text(
        "--*++*-- Time: 1.000000e+01s. Step no: 1804/200000. Current step-size: 2.500000e-01s\n",
        encoding="utf-8",
    )

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert snapshot["adaptive_total_steps"] == 200000


def _backdate(path: Path, age_s: float) -> None:
    old = time.time() - age_s
    os.utime(path, (old, old))


_TPL_HEADER = (
    "'OLGA 2025.1.0'\n"
    "'TIME PLOT'\n"
    "CATALOG\n"
    "1\n"
    "PT 'POSITION:' 'INLET' '(PA)' 'Pressure'\n"
    "TIME SERIES  ' (S)  '\n"
)


def test_growing_tpl_keeps_run_active_with_tpl_simulation_time(tmp_path: Path) -> None:
    out_path = tmp_path / "case.out"
    out_path.write_text("OLGA solver log header, no timestep line yet\n", encoding="utf-8")
    _backdate(out_path, diagnostics._LIVENESS_STALE_SECONDS + 60.0)
    (tmp_path / "case.tpl").write_text(
        _TPL_HEADER + "0.000000e+00 5.000000e+06\n9.000000e+02 5.100000e+06\n",
        encoding="utf-8",
    )

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert snapshot["activity_status"] == "active"
    assert snapshot["simulation_time_s"] == 900.0
    assert snapshot["age_seconds"] is not None
    assert snapshot["age_seconds"] <= diagnostics._LIVENESS_STALE_SECONDS


def test_growing_ppl_keeps_run_active(tmp_path: Path) -> None:
    out_path = tmp_path / "case.out"
    out_path.write_text(
        "--*++*-- Time: 10s. Step no: 2/200. Current step-size: 0.5s\n",
        encoding="utf-8",
    )
    _backdate(out_path, diagnostics._LIVENESS_STALE_SECONDS + 60.0)
    (tmp_path / "case.ppl").write_text(
        "'OLGA 2025.1.0'\n'PROFILE PLOT'\nTIME SERIES  ' (S)  '\n1.800000e+03\n",
        encoding="utf-8",
    )

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert snapshot["activity_status"] == "active"
    assert snapshot["simulation_time_s"] == 10.0


def test_out_timestep_keeps_priority_over_tpl_time(tmp_path: Path) -> None:
    out_path = tmp_path / "case.out"
    out_path.write_text(
        "--*++*-- Time: 10s. Step no: 2/200. Current step-size: 0.5s\n",
        encoding="utf-8",
    )
    (tmp_path / "case.tpl").write_text(
        _TPL_HEADER + "9.000000e+02 5.100000e+06\n",
        encoding="utf-8",
    )

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert snapshot["activity_status"] == "active"
    assert snapshot["simulation_time_s"] == 10.0


def test_tpl_tail_read_is_byte_bounded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out_path = tmp_path / "case.out"
    out_path.write_text("OLGA solver log header, no timestep line yet\n", encoding="utf-8")
    (tmp_path / "case.tpl").write_bytes(
        _TPL_HEADER.encode("utf-8")
        + b"0.000000e+00 5.000000e+06\n"
        + b"x" * (diagnostics._SNAPSHOT_TAIL_BYTES + 128)
        + b"\n9.000000e+02 5.100000e+06\n"
    )
    real_open = Path.open
    requested_sizes: list[int] = []

    class TrackingHandle:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def fileno(self):
            return self.wrapped.fileno()

        def seek(self, *args):
            return self.wrapped.seek(*args)

        def read(self, size=-1):
            requested_sizes.append(size)
            return self.wrapped.read(size)

    def tracked(path: Path, *args, **kwargs):
        return TrackingHandle(real_open(path, *args, **kwargs))

    monkeypatch.setattr(Path, "open", tracked)

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert requested_sizes and all(0 <= size <= diagnostics._SNAPSHOT_TAIL_BYTES for size in requested_sizes)
    assert snapshot["simulation_time_s"] == 900.0
