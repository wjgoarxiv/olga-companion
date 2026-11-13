from __future__ import annotations

from olga_companion.run_outputs import diagnose_run_failure


def test_opi_zero_exit_batch_failure_is_actionable_and_never_auto_retried() -> None:
    failure = diagnose_run_failure(
        exit_code=0,
        engine_failed=True,
        log_tail="0 of 1 case(s) finished successfully\n1 case(s) failed",
        command=["/init", "/opt/olga/opi.exe", "/opt/olga/opi.exe", "-f", "case.genkey"],
        output_count=0,
    )

    assert failure is not None
    assert failure["code"] == "opi_engine_start_failed"
    assert "exit 0" in failure["detail"]
    assert "native" in failure["action"].lower()
    assert failure["auto_retry_safe"] is False


def test_native_communication_exit_is_mapped() -> None:
    failure = diagnose_run_failure(
        exit_code=57,
        engine_failed=False,
        log_tail="",
        command=["/opt/olga/OLGA-2022.1.0.exe", "-nthreads", "12", "case.genkey"],
        output_count=0,
    )

    assert failure is not None
    assert failure["code"] == "native_communication_failure"
    assert "57" in failure["detail"]
    assert all(f"{step}." in failure["action"] for step in (1, 2, 3))
    assert "automatic" not in failure["action"].lower()
    assert failure["auto_retry_safe"] is False


def test_clean_completion_has_no_failure_diagnostic() -> None:
    assert diagnose_run_failure(
        exit_code=0,
        engine_failed=False,
        log_tail="NORMAL STOP IN EXECUTION",
        command=["/opt/olga/OLGA-2022.1.0.exe", "case.genkey"],
        output_count=4,
    ) is None


def test_cancelled_run_reads_as_cancelled_not_as_a_case_failure() -> None:
    # Windows ERROR_CANCELLED (1223) is what the child reports after the user cancels.
    failure = diagnose_run_failure(
        exit_code=1223,
        engine_failed=False,
        log_tail="",
        command=["/opt/olga/OLGA-2022.1.0.exe", "case.genkey"],
        output_count=0,
        cancelled=True,
    )

    assert failure is not None
    assert failure["code"] == "run_cancelled"
    assert "cancel" in failure["title"].lower()
    assert "failed" not in failure["title"].lower()
    assert "You cancelled this run" in failure["detail"]
    assert "inspect" not in failure["detail"].lower()
    for advice in ("correct", "review the log"):
        assert advice not in failure["action"].lower()
    assert failure["auto_retry_safe"] is False


def test_timed_out_run_names_the_time_limit() -> None:
    failure = diagnose_run_failure(
        exit_code=1460,  # Windows ERROR_TIMEOUT
        engine_failed=False,
        log_tail="",
        command=["/opt/olga/OLGA-2022.1.0.exe", "case.genkey"],
        output_count=0,
        timed_out=True,
    )

    assert failure is not None
    assert failure["code"] == "run_timed_out"
    assert "time limit" in failure["detail"].lower()
    assert "raise the run time limit" in failure["action"].lower()
    assert "correct the reported condition" not in failure["action"]
    assert failure["auto_retry_safe"] is False


def test_a_real_nonzero_exit_keeps_the_process_failed_text() -> None:
    failure = diagnose_run_failure(
        exit_code=1,
        engine_failed=True,
        log_tail="FATAL ERROR",
        command=["/opt/olga/OLGA-2022.1.0.exe", "case.genkey"],
        output_count=0,
        cancelled=False,
        timed_out=False,
    )

    assert failure is not None
    assert failure["code"] == "native_process_failed"
    assert failure["title"] == "OLGA process failed"
    assert failure["detail"] == (
        "The native process returned exit 1; inspect the captured solver log for the case-specific cause."
    )
    assert failure["action"] == "Review the log and correct the reported condition before starting another run."


def test_a_helper_that_never_reported_is_not_blamed_on_the_case() -> None:
    # Bug report 2026-11-13 (0.1.7, enterprise PC): the Explorer helper never
    # published a status, the app ended the run with its own exit 125, and the
    # message told the user to fix the case from a solver log that did not exist.
    failure = diagnose_run_failure(
        exit_code=125,
        engine_failed=True,
        log_tail="",
        command=["C:/OLGA/OLGA-2025.1.0.exe", "case.genkey"],
        output_count=0,
        helper_problem="Explorer broker did not publish a valid launch status before the startup deadline.",
    )

    assert failure is not None
    assert failure["code"] == "run_helper_failed"
    assert "125" not in failure["detail"]
    assert "solver log" not in failure["detail"]
    assert "security software" in failure["action"].lower()
    assert "olga-explorer-broker.exe" in failure["action"]
    assert failure["auto_retry_safe"] is False


def test_helper_problem_does_not_hide_a_cancellation() -> None:
    failure = diagnose_run_failure(
        exit_code=1223,
        engine_failed=False,
        log_tail="",
        command=["C:/OLGA/OLGA-2025.1.0.exe", "case.genkey"],
        output_count=0,
        cancelled=True,
        helper_problem="Explorer broker heartbeat is stale.",
    )

    assert failure is not None
    assert failure["code"] == "run_cancelled"


def test_olga_that_cannot_load_its_dlls_says_how_to_start_the_app() -> None:
    # Measured 2026-11-13: an app started from a WSL shell carries the "load System32
    # DLLs first" process flag, and OLGA then exits with 0xC0000139 before any output.
    failure = diagnose_run_failure(
        exit_code=0xC0000139,
        engine_failed=True,
        log_tail="",
        command=["C:/OLGA/OLGA-2022.1.0.exe", "case.genkey"],
        output_count=0,
    )

    assert failure is not None
    assert failure["code"] == "olga_dll_load_failed"
    assert "Start menu" in failure["action"]
    assert failure["auto_retry_safe"] is False
