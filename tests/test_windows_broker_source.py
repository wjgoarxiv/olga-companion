from __future__ import annotations

from pathlib import Path


def _broker_sources() -> tuple[Path, ...]:
    source_dir = Path(__file__).parents[1] / "src" / "olga_companion" / "broker"
    sources = tuple(source_dir.glob("OlgaExplorerBroker*.cs"))
    return tuple(
        sorted(
            sources,
            key=lambda source: (source.name != "OlgaExplorerBroker.cs", source.name),
        )
    )


def _broker_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in _broker_sources())


def test_checked_in_broker_sources_stay_below_pure_line_ceiling() -> None:
    sources = _broker_sources()

    assert sources
    for source in sources:
        pure_lines = [
            line
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("//")
        ]
        assert len(pure_lines) <= 249, source


def test_checked_in_broker_source_enforces_suspended_job_launch_without_shell() -> None:
    source = _broker_source()

    assert "CreateProcessW" in source
    assert "CreateSuspended" in source
    assert "AssignProcessToJobObject" in source
    assert "JobObjectLimitKillOnJobClose" in source
    assert "SetHandleInformation" in source
    assert source.index("AssignProcessToJobObject(job, child.hProcess)") < source.index(
        "ResumeThread(child.hThread)"
    )
    assert "cmd.exe" not in source.lower()
    assert "powershell" not in source.lower()
    assert "Process.Start" not in source
    assert 'new FileStream("NUL"' not in source
    assert 'Path.Combine(baseDir, "broker-stdin.empty")' in source


def test_checked_in_broker_duplicate_loser_cannot_write_status_or_terminate_job() -> (
    None
):
    source = _broker_source()
    main = source[
        source.index("public static int Main()") : source.index(
            "private static void ValidateRequest"
        )
    ]

    assert "bool claimWon = false;" in main
    assert main.index("File.Move(requestPath, claimedPath);") < main.index(
        "claimWon = true;"
    )
    assert main.index("claimWon = true;") < main.index("WriteStatus(")
    assert "if (request != null && claimWon)" in main
    catch_body = main[main.index("catch (Exception ex)") : main.index("finally")]
    assert catch_body.index("if (request != null && claimWon)") < catch_body.index(
        "TerminateJobObject"
    )
    assert catch_body.index("if (request != null && claimWon)") < catch_body.index(
        "WriteStatus"
    )


def test_checked_in_broker_bounds_job_failure_cleanup_and_tracks_assignment() -> None:
    source = _broker_source()

    assert "bool jobAssigned = false;" in source
    assert source.index("AssignProcessToJobObject(job, child.hProcess)") < source.index(
        "jobAssigned = true;"
    )
    assert "TerminateProcess" in source
    catch_body = source[source.index("catch (Exception ex)") : source.index("finally")]
    assert "if (jobAssigned)" in catch_body
    assert "TerminateJobObject" in catch_body
    assert "TerminateProcess" in catch_body
    assert "WaitForSingleObject(child.hProcess, Infinite)" not in source
    assert "TerminationWaitMs" in source


def test_checked_in_broker_locks_and_hashes_engine_and_case_through_execution() -> None:
    source = _broker_source()
    main = source[
        source.index("public static int Main()") : source.index(
            "private static void ValidateRequest"
        )
    ]

    engine_lock = main.index(
        "new FileStream(request.engine, FileMode.Open, FileAccess.Read, FileShare.Read)"
    )
    case_lock = main.index(
        "new FileStream(stagedPath, FileMode.Open, FileAccess.Read, FileShare.Read)"
    )
    final_engine_hash = main.index("HashEquals(engineLock, request.engine_sha256)")
    final_case_hash = main.index("HashEquals(caseLock, request.staged_case_sha256)")
    launch = main.index("CreateProcessW")
    wait = main.index("WaitForSingleObject(child.hProcess")
    assert engine_lock < final_engine_hash < launch < wait
    assert case_lock < final_case_hash < launch < wait
    assert "private static bool HashEquals(Stream stream, string expected)" in source


def test_a_busy_status_file_never_stops_a_running_simulation() -> None:
    # A reader holding broker-status.json open made File.Replace throw mid-run, and the catch-all
    # then terminated OLGA with exit 125. A heartbeat that cannot write must skip, not kill.
    source = _broker_source()
    loop = source[source.index("while (true)") : source.index("GetExitCodeProcess(child.hProcess, out rawExit)) throw")]
    assert "TryWriteStatus(" in loop
    assert " WriteStatus(statusPath, request, \"running\"" not in loop
    write = source[source.index("private static void WriteStatus") : source.index("private static bool HashEquals")]
    assert "catch (IOException)" in write
    assert "Thread.Sleep(" in write
