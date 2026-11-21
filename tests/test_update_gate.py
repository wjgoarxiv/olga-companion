"""Installing an update stops the local backend, so it must never do that silently
to a run: the gate refuses while any run is starting, running or of unknown
status, and once it says "safe" it shares one lock with the launch path so no run
can slip in between the check and the stop."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from olga_companion import run_records, run_update_gate, runner, sidecar, sweep_launch
from olga_companion.agent import session_token
from olga_companion.genkey_static import OlgaInputError


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sandbox = tmp_path / "sandbox"
    (sandbox / "runs").mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    return sandbox / "runs"


@pytest.fixture(autouse=True)
def _clean_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runner.release_update_gate()
    runner._RELEASED_PREPARES.clear()
    monkeypatch.setattr(runner, "sandbox_root", lambda: tmp_path / "no-sandbox")
    yield
    runner.release_update_gate()
    runner._RELEASED_PREPARES.clear()
    with runner._REGISTRY_LOCK:
        runner._RUNS.pop("gate-live-run", None)


def _live_state(selection_id: str = "gate-selection") -> SimpleNamespace:
    return SimpleNamespace(selection_id=selection_id, popen=SimpleNamespace(poll=lambda: None))


def test_idle_backend_is_safe_and_then_refuses_every_new_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    launch = Mock(return_value={"run_id": "must-not-launch"})
    monkeypatch.setattr(runner, "_execute_run_claimed", launch)

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is True and gate["blocking"] == []
    with pytest.raises(OlgaInputError, match="update"):
        runner.execute_run("case.genkey", approved=True, selection_id="after-latch")
    launch.assert_not_called()


def test_live_run_blocks_the_gate_and_leaves_launching_open(monkeypatch: pytest.MonkeyPatch) -> None:
    with runner._REGISTRY_LOCK:
        runner._RUNS["gate-live-run"] = _live_state()

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is False
    assert [item["run_id"] for item in gate["blocking"]] == ["gate-live-run"]
    assert "Run" in gate["message"] and "cancel" in gate["message"].lower()
    # A refused gate must not latch: the user is still working.
    launch = Mock(return_value={"run_id": "still-allowed"})
    monkeypatch.setattr(runner, "_execute_run_claimed", launch)
    assert runner.execute_run("case.genkey", approved=True, selection_id="other") == {"run_id": "still-allowed"}


def test_a_run_that_is_still_launching_blocks_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = threading.Event(), threading.Event()

    def slow_launch(*_a, **_k):
        entered.set()
        assert release.wait(timeout=3)
        return {"run_id": "launched"}

    monkeypatch.setattr(runner, "_execute_run_claimed", slow_launch)
    worker = threading.Thread(
        target=lambda: runner.execute_run("case.genkey", approved=True, selection_id="slow")
    )
    worker.start()
    try:
        assert entered.wait(timeout=3)
        # Popen has happened (or is about to) but nothing is in _RUNS yet.
        gate = runner.begin_update_gate("test")
        assert gate["safe"] is False and gate["starting"] == 1
    finally:
        release.set()
        worker.join(timeout=3)

    assert runner.begin_update_gate("test")["safe"] is True


def test_launch_without_a_selection_claim_is_also_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = threading.Event(), threading.Event()

    def slow_launch(*_a, **_k):
        entered.set()
        assert release.wait(timeout=3)
        return {"run_id": "launched"}

    monkeypatch.setattr(runner, "_execute_run_claimed", slow_launch)
    worker = threading.Thread(target=lambda: runner.execute_run("case.genkey", approved=True))
    worker.start()
    try:
        assert entered.wait(timeout=3)
        assert runner.begin_update_gate("test")["safe"] is False
    finally:
        release.set()
        worker.join(timeout=3)


def test_a_failed_launch_releases_its_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_execute_run_claimed", Mock(side_effect=OlgaInputError("refused")))
    with pytest.raises(OlgaInputError):
        runner.execute_run("case.genkey", approved=True, selection_id="fails")

    assert runner.begin_update_gate("test")["safe"] is True


def test_gate_and_launch_cannot_both_win(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whichever takes the shared lock first decides; the other side sees it."""

    def register_live_run(*_a, **_k):
        with runner._REGISTRY_LOCK:
            runner._RUNS["gate-live-run"] = _live_state("race")
        return {"run_id": "gate-live-run"}

    monkeypatch.setattr(runner, "_execute_run_claimed", register_live_run)

    for _ in range(40):
        runner.release_update_gate()
        with runner._REGISTRY_LOCK:
            runner._RUNS.pop("gate-live-run", None)
        barrier = threading.Barrier(2)
        outcome: dict[str, bool] = {}

        def start() -> None:
            barrier.wait(timeout=3)
            try:
                runner.execute_run("case.genkey", approved=True)
                outcome["started"] = True
            except OlgaInputError:
                outcome["started"] = False

        def gate() -> None:
            barrier.wait(timeout=3)
            outcome["safe"] = runner.begin_update_gate("test")["safe"]

        threads = [threading.Thread(target=start), threading.Thread(target=gate)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        # A "safe" answer with a run that went on to start is the silent kill.
        assert not (outcome["safe"] and outcome["started"])
        # And a refused gate means a run really is there to protect.
        assert outcome["safe"] or outcome["started"]


def test_sweep_holds_the_gate_across_the_gaps_between_child_launches(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []
    state = SimpleNamespace()

    def fake_body(*_a, **_k):
        # Between two child runs nothing is in _RUNS and no execute_run is in flight.
        seen.append(runner.begin_update_gate("test")["safe"])

    monkeypatch.setattr(sweep_launch, "_launch_sweep_locked", fake_body)
    sweep_launch.launch_sweep(state, "plan", Mock())  # type: ignore[arg-type]

    assert seen == [False]
    assert runner.begin_update_gate("test")["safe"] is True


def test_sweep_cannot_start_once_the_gate_is_latched(monkeypatch: pytest.MonkeyPatch) -> None:
    body = Mock()
    monkeypatch.setattr(sweep_launch, "_launch_sweep_locked", body)
    runner.begin_update_gate("test")

    with pytest.raises(OlgaInputError, match="update"):
        sweep_launch.launch_sweep(SimpleNamespace(), "plan", Mock())  # type: ignore[arg-type]
    body.assert_not_called()


def _receipt(run_id: str, *, phase: str = "running", broker: bool = True) -> dict:
    receipt = {
        "schema_version": 1,
        "run_id": run_id,
        "phase": phase,
        "state": {"prepared": "prepared", "running": "running", "terminal": "completed"}[phase],
        "source": {"name": "case.genkey", "sha256": "a" * 64, "staged_sha256": "a" * 64},
        "companions": [],
        "runtime": {"candidate_id": "r", "runtime_id": "r", "version": "2022.1.0", "kind": "engine", "exe": "/olga/opi.exe"},
        "selection_id": "selection",
        "validation": {"valid": True, "command": {}},
        "timestamps": {"prepared_at": "2026-01-01T00:00:00Z", "started_at": None, "finished_at": None},
        "command": ["/olga/opi.exe", "case.genkey"],
        "exit_code": None,
        "failure": None,
        "outputs": [],
    }
    if broker:
        receipt["broker_run"] = {"request_id": "r" * 8, "protocol": runner.BROKER_PROTOCOL, "status_name": "s.json", "cancel_name": "c.json", "started_wall_ns": 1}
    return receipt


def _write(runs: Path, run_id: str, receipt: dict) -> Path:
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)
    run_records.write_run_record(run_dir, receipt)
    return run_dir


def test_an_interrupted_broker_run_left_by_an_earlier_session_blocks_the_gate(runs: Path) -> None:
    _write(runs, "after-restart", _receipt("after-restart"))

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is False
    assert gate["blocking"] == [{"run_id": "after-restart", "state": "supervision_unknown"}]
    assert runner.begin_update_gate("test")["safe"] is False  # still not latched


@pytest.mark.parametrize("state", ["running", "finalizing"])
def test_running_and_finalizing_receipts_block_the_gate(
    runs: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    _write(runs, "other-session", _receipt("other-session"))
    monkeypatch.setattr(runner, "_status_from_receipt", lambda record, _dir: {"state": state})

    assert runner.begin_update_gate("test")["blocking"] == [{"run_id": "other-session", "state": state}]


def test_terminal_receipts_and_launches_that_never_happened_do_not_block(runs: Path) -> None:
    _write(runs, "finished", _receipt("finished", phase="terminal"))
    (runs / "crashed-before-receipt").mkdir()
    staged = runs / "crashed-after-staging"
    staged.mkdir()
    (staged / "case.genkey").write_text("CASE LABEL=x\nENDCASE\n", encoding="utf-8")
    (runs / "stray.txt").write_text("not a run", encoding="utf-8")

    assert runner.begin_update_gate("test")["safe"] is True


@pytest.mark.parametrize(
    "trace",
    ["broker-status.json", "broker-request.json", "broker-cancel.json", "olga-explorer-broker.exe", "run.log", "case.out", "case.TPL", "case.ppl"],
)
def test_a_run_directory_that_lost_its_receipt_after_launching_blocks(runs: Path, trace: str) -> None:
    lost = runs / "lost-receipt"
    lost.mkdir()
    (lost / "case.genkey").write_text("CASE LABEL=x\nENDCASE\n", encoding="utf-8")
    (lost / trace).write_text("x", encoding="utf-8")

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is False
    assert gate["blocking"] == [{"run_id": "lost-receipt", "state": "unreadable_receipt"}]


def test_a_run_directory_that_cannot_be_listed_blocks(runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (runs / "unlistable").mkdir()
    monkeypatch.setattr(run_update_gate, "_has_launch_trace", Mock(side_effect=PermissionError("denied")))

    assert runner.begin_update_gate("test")["blocking"] == [{"run_id": "unlistable", "state": "unreadable_receipt"}]


@pytest.mark.parametrize("broker", [True, False])
def test_a_receipt_with_no_recorded_end_blocks_even_when_no_process_is_known(runs: Path, broker: bool) -> None:
    # "completion is unknown" is not "ended"; the gate does not guess who owned the process.
    _write(runs, "unknown-end", _receipt("unknown-end", broker=broker))

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is False
    assert [item["run_id"] for item in gate["blocking"]] == ["unknown-end"]


def test_a_run_cannot_start_while_the_receipts_are_being_scanned(
    runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launch = Mock(return_value={"run_id": "slipped-in"})
    monkeypatch.setattr(runner, "_execute_run_claimed", launch)
    real_scan = run_update_gate.scan_open_receipts
    attempts: list[str] = []

    def scan_then_try_to_start(ctx):
        result = real_scan(ctx)
        try:
            runner.execute_run("case.genkey", approved=True, selection_id="mid-scan")
            attempts.append("started")
        except OlgaInputError:
            attempts.append("refused")
        return result

    monkeypatch.setattr(run_update_gate, "scan_open_receipts", scan_then_try_to_start)

    assert runner.begin_update_gate("test")["safe"] is True
    assert attempts == ["refused"]
    launch.assert_not_called()


def test_a_refused_gate_reopens_launching_after_its_scan(runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(runs, "open-run", _receipt("open-run"))
    launch = Mock(return_value={"run_id": "ok"})
    monkeypatch.setattr(runner, "_execute_run_claimed", launch)

    assert runner.begin_update_gate("test")["safe"] is False

    assert runner.execute_run("case.genkey", approved=True, selection_id="after") == {"run_id": "ok"}


def test_concurrent_prepares_cannot_hand_the_second_a_latch_the_first_gives_back(
    runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused A holds the latch while scanning; B must not adopt it, then see A release it."""
    a_scanning, let_a_finish = threading.Event(), threading.Event()
    scans: list[str] = []
    answers = iter([[{"run_id": "still-running", "state": "running"}], []])

    def scan(_ctx):
        scans.append("scan")
        answer = next(answers)
        if len(scans) == 1:
            a_scanning.set()
            assert let_a_finish.wait(timeout=3)
        return answer

    monkeypatch.setattr(run_update_gate, "scan_open_receipts", scan)
    results: dict[str, dict] = {}

    first = threading.Thread(target=lambda: results.update(a=runner.begin_update_gate("test")))
    first.start()
    assert a_scanning.wait(timeout=3)
    second = threading.Thread(target=lambda: results.update(b=runner.begin_update_gate("test")))
    second.start()
    second.join(timeout=0.3)
    assert second.is_alive()  # B waits for A instead of reading A's temporary latch
    let_a_finish.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert results["a"]["safe"] is False
    assert results["b"]["safe"] is True
    assert runner._UPDATE_LATCHED is True
    with pytest.raises(OlgaInputError, match="update"):
        runner.execute_run("case.genkey", approved=True, selection_id="after-safe-reply")


def test_a_refused_retry_keeps_an_earlier_successful_latch(runs: Path) -> None:
    assert runner.begin_update_gate("test")["safe"] is True
    _write(runs, "appeared-later", _receipt("appeared-later"))

    assert runner.begin_update_gate("test")["safe"] is False
    assert runner._UPDATE_LATCHED is True


@pytest.mark.parametrize("kind", ["malformed", "symlink-receipt", "symlink-directory", "wrong-run-id"])
def test_an_unreadable_receipt_is_not_proof_the_run_ended(runs: Path, tmp_path: Path, kind: str) -> None:
    target = runs / "suspect"
    if kind == "malformed":
        target.mkdir()
        (target / "run.json").write_text("{not json", encoding="utf-8")
    elif kind == "symlink-receipt":
        target.mkdir()
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps(_receipt("suspect", phase="terminal")), encoding="utf-8")
        (target / "run.json").symlink_to(outside)
    elif kind == "symlink-directory":
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        target.symlink_to(elsewhere, target_is_directory=True)
    else:
        target.mkdir()
        (target / "run.json").write_text(json.dumps(_receipt("someone-else", phase="terminal")), encoding="utf-8")

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is False
    assert gate["blocking"] == [{"run_id": "suspect", "state": "unreadable_receipt"}]
    assert "suspect" in gate["message"]


def test_an_open_run_behind_a_hundred_newer_finished_runs_is_still_found(runs: Path) -> None:
    old = _write(runs, "oldest-open", _receipt("oldest-open"))
    os.utime(old / "run.json", (1, 1))
    for index in range(150):
        _write(runs, f"finished-{index:03d}", _receipt(f"finished-{index:03d}", phase="terminal"))

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is False
    assert gate["blocking"] == [{"run_id": "oldest-open", "state": "supervision_unknown"}]


def test_a_scan_that_hits_its_limit_refuses_instead_of_guessing(
    runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_update_gate, "MAX_SCANNED_RUN_DIRECTORIES", 3)
    for index in range(4):
        _write(runs, f"finished-{index}", _receipt(f"finished-{index}", phase="terminal"))

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is False and gate["confirmed"] is False
    assert runner._UPDATE_LATCHED is False


def test_unreadable_run_directory_fails_closed(runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a, **_k):
        raise PermissionError("denied")

    monkeypatch.setattr(run_update_gate.os, "scandir", broken)

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is False and gate["confirmed"] is False
    assert "could not confirm" in gate["message"].lower()
    assert runner._UPDATE_LATCHED is False


def test_routes_require_the_session_token_and_a_prepare_id() -> None:
    client = TestClient(sidecar.app)
    token = {"X-Session-Token": session_token.boot_token()}
    prepare_id = {"X-Update-Prepare-Id": "native-abc-123"}
    assert client.post("/api/update/prepare", headers=prepare_id).status_code == 401
    assert client.post("/api/update/release", headers=prepare_id).status_code == 401
    assert client.post("/api/update/prepare", headers=token).status_code == 400
    assert client.post("/api/update/prepare", headers={**token, "X-Update-Prepare-Id": "bad id\r\n"}).status_code == 400

    response = client.post("/api/update/prepare", headers={**token, **prepare_id})

    assert response.status_code == 200 and response.json()["safe"] is True
    assert runner._UPDATE_LATCHED is True
    assert client.post("/api/update/release", headers={**token, "X-Update-Prepare-Id": "other"}).json() == {"released": False}
    assert runner._UPDATE_LATCHED is True
    assert client.post("/api/update/release", headers={**token, **prepare_id}).json() == {"released": True}
    assert runner._UPDATE_LATCHED is False


def test_a_safe_answer_is_never_withdrawn_by_the_passage_of_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # The native side holds a positive answer and has not stopped the backend yet (a
    # scheduling delay, a frozen app, a laptop waking up). No amount of elapsed time may
    # let a run start before that stop.
    launch = Mock(return_value={"run_id": "must-not-start"})
    monkeypatch.setattr(runner, "_execute_run_claimed", launch)
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    assert runner.begin_update_gate("native-1")["safe"] is True

    for later in (131.0, 4000.0, 10**6):
        now[0] = later
        with pytest.raises(OlgaInputError, match="update"):
            runner.execute_run("case.genkey", approved=True, selection_id=f"after-{later}")
    launch.assert_not_called()


def test_only_the_prepare_that_took_the_latch_can_give_it_back() -> None:
    assert runner.begin_update_gate("native-1")["safe"] is True

    runner.release_update_gate("someone-else")
    assert runner._UPDATE_LATCHED is True

    runner.release_update_gate("native-1")
    assert runner._UPDATE_LATCHED is False


def test_another_attempt_cannot_take_over_or_release_a_latch_it_does_not_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A got "safe" and its native stop is still pending; B prepares, then gives up.
    launch = Mock(return_value={"run_id": "must-not-start"})
    monkeypatch.setattr(runner, "_execute_run_claimed", launch)
    assert runner.begin_update_gate("a")["safe"] is True

    second = runner.begin_update_gate("b")

    assert second["safe"] is False and second["confirmed"] is True
    assert "already closed launching" in second["message"]
    assert runner.release_update_gate("b") is False  # b never owned it
    for attempt in ("after-b-gave-up", "and-again"):
        with pytest.raises(OlgaInputError, match="update"):
            runner.execute_run("case.genkey", approved=True, selection_id=attempt)
    launch.assert_not_called()
    # Only a's own release reopens launching.
    assert runner.release_update_gate("a") is True
    assert runner._UPDATE_LATCHED is False


def test_the_same_attempt_may_ask_again_without_losing_its_latch(runs: Path) -> None:
    assert runner.begin_update_gate("a")["safe"] is True

    assert runner.begin_update_gate("a")["safe"] is True

    assert runner._UPDATE_LATCHED is True
    assert runner.release_update_gate("a") is True


def test_a_refused_prepare_gives_back_only_its_own_temporary_latch(runs: Path) -> None:
    assert runner.begin_update_gate("first")["safe"] is True
    _write(runs, "appeared-later", _receipt("appeared-later"))

    # The same owner asking again sees the new open run and is refused, but keeps its latch.
    assert runner.begin_update_gate("first")["safe"] is False

    assert runner._UPDATE_LATCHED is True
    runner.release_update_gate("first")
    assert runner._UPDATE_LATCHED is False


def test_a_run_whose_status_cannot_be_read_is_unconfirmed_and_leaves_no_latch() -> None:
    class Unreadable:
        def poll(self):
            raise PermissionError("broker status is being replaced")

    with runner._REGISTRY_LOCK:
        runner._RUNS["gate-live-run"] = SimpleNamespace(selection_id="x", popen=Unreadable())

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is False and gate["confirmed"] is False
    assert runner._UPDATE_LATCHED is False


def test_an_active_run_answers_at_once_without_closing_launches_for_a_scan(
    runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with runner._REGISTRY_LOCK:
        runner._RUNS["gate-live-run"] = _live_state()
    scans: list[int] = []
    monkeypatch.setattr(run_update_gate, "scan_open_receipts", lambda _ctx: scans.append(1) or [])

    gate = runner.begin_update_gate("test")

    assert gate["safe"] is False and scans == []
    assert runner._UPDATE_LATCHED is False


def test_a_run_with_no_recorded_end_is_not_told_to_cancel_it(runs: Path) -> None:
    _write(runs, "no-end", _receipt("no-end", broker=False))

    message = runner.begin_update_gate("test")["message"]

    assert "no-end" in message
    assert "cannot be cancelled" in message


def test_a_release_that_overtakes_its_prepare_leaves_launching_open(
    runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The native side gave up on attempt "c" and sent its release while the prepare was still
    # queued or scanning: the prepare must not latch afterwards on an answer nobody will read.
    entered, let_go = threading.Event(), threading.Event()
    real_scan = run_update_gate.scan_open_receipts

    def slow_scan(ctx):
        entered.set()
        assert let_go.wait(timeout=3)
        return real_scan(ctx)

    monkeypatch.setattr(run_update_gate, "scan_open_receipts", slow_scan)
    result: dict[str, dict] = {}
    prepare = threading.Thread(target=lambda: result.update(c=runner.begin_update_gate("c")))
    prepare.start()
    assert entered.wait(timeout=3)

    runner.release_update_gate("c")  # arrives mid-scan
    let_go.set()
    prepare.join(timeout=3)

    assert result["c"]["safe"] is False
    assert runner._UPDATE_LATCHED is False
    launch = Mock(return_value={"run_id": "ok"})
    monkeypatch.setattr(runner, "_execute_run_claimed", launch)
    assert runner.execute_run("case.genkey", approved=True, selection_id="free") == {"run_id": "ok"}


def test_a_release_that_arrives_before_its_prepare_cancels_that_prepare() -> None:
    runner.release_update_gate("early")

    gate = runner.begin_update_gate("early")

    assert gate["safe"] is False and "cancelled" in gate["message"]
    assert runner._UPDATE_LATCHED is False
    assert runner.begin_update_gate("a-fresh-attempt")["safe"] is True


def test_a_safe_answer_requires_the_latch_to_still_be_held_when_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same attempt asks again; something reopens launching during the second scan.
    assert runner.begin_update_gate("a")["safe"] is True
    real_scan = run_update_gate.scan_open_receipts

    def scan_while_launching_is_reopened(ctx):
        runner.release_update_gate()  # unconditional reopen, as a test fixture or operator would
        return real_scan(ctx)

    monkeypatch.setattr(run_update_gate, "scan_open_receipts", scan_while_launching_is_reopened)

    assert runner.begin_update_gate("a")["safe"] is False
