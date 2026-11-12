"""Popen-compatible supervision for the Explorer broker and solver child."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from .windows_broker_protocol import DEFAULT_STARTUP_TIMEOUT_S
from .windows_broker_status import (
    broker_heartbeat_is_live,
    read_broker_status,
    request_broker_cancel,
)


class BrokerProcess:
    """Popen-compatible subset whose completion is defined only by broker status."""

    def __init__(
        self,
        dispatcher: subprocess.Popen[bytes] | Any,
        run_dir: Path,
        request_id: str,
        startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
    ) -> None:
        self.dispatcher = dispatcher
        self.run_dir = run_dir
        self.request_id = request_id
        self.startup_deadline = time.monotonic() + startup_timeout_s
        self._supervision_error: str | None = None
        self._supervision_cancelled = False
        self._last_status: dict[str, Any] | None = None

    @property
    def supervision_error(self) -> str | None:
        return self._supervision_error

    def status(self) -> dict[str, Any] | None:
        try:
            status = read_broker_status(self.run_dir, self.request_id)
        except ValueError as exc:
            self._fail_supervision(str(exc))
            return None
        if status is not None:
            self._last_status = status
        return status

    def _fail_supervision(self, detail: str) -> None:
        if self._supervision_error is None:
            self._supervision_error = detail
        if not self._supervision_cancelled:
            self._supervision_cancelled = True
            try:
                request_broker_cancel(self.run_dir, self.request_id, reason="killed")
            except (OSError, ValueError):
                return

    def _heartbeat_problem(self, status: Mapping[str, Any]) -> str | None:
        raw = status.get("updated_utc")
        if not broker_heartbeat_is_live(raw):
            return "Explorer broker heartbeat is stale."
        return None

    def poll(self) -> int | None:
        # Reap Explorer when it exits, but never use its exit code as solver
        # completion. Only a bound terminal broker status can complete a run.
        dispatcher_exit = self.dispatcher.poll()
        current_status = self.status()
        status = current_status if current_status is not None else self._last_status
        if self._supervision_error is not None:
            return 125
        if status is not None:
            if status["state"] == "terminal":
                return int(status["child_exit_code"])
            heartbeat_problem = self._heartbeat_problem(status)
            if heartbeat_problem is not None and (
                dispatcher_exit is not None
                or time.monotonic() >= self.startup_deadline
            ):
                self._fail_supervision(heartbeat_problem)
                return 125
            return None
        if time.monotonic() >= self.startup_deadline:
            self._fail_supervision(
                "Explorer broker did not publish a valid launch status before "
                "the startup deadline."
            )
            return 125
        return None

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            result = self.poll()
            if result is not None:
                return result
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("Explorer broker", timeout)
            time.sleep(0.05)

    def _cancel(self, reason: str) -> None:
        request_broker_cancel(self.run_dir, self.request_id, reason=reason)

    def terminate(self) -> None:
        self._cancel("cancelled")

    def kill(self) -> None:
        self._cancel("killed")
