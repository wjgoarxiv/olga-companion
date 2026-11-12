"""Fake OLGA executable for M3 runner tests.

Mimics the observable contract the runner relies on: prints log lines, writes a
.out marker beside the case copy in its cwd, and exits. Behavior knobs come
from environment variables so the command surface stays identical to a real
run: FAKE_OLGA_SLEEP (seconds), FAKE_OLGA_EXIT (exit code).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("FAKE-OLGA error: no case file argument", file=sys.stderr, flush=True)
        return 2
    case = Path(sys.argv[1])
    print(f"FAKE-OLGA starting case {case.name}", flush=True)
    child_pid_file = os.environ.get("FAKE_OLGA_CHILD_PID_FILE")
    if child_pid_file:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        Path(child_pid_file).write_text(str(child.pid), encoding="utf-8")
    sleep_s = float(os.environ.get("FAKE_OLGA_SLEEP", "0"))
    if sleep_s > 0:
        time.sleep(sleep_s)
    out = Path.cwd() / (case.stem + ".out")
    out.write_text("FAKE OLGA OUTPUT\nSIMULATION COMPLETE\n", encoding="utf-8")
    if os.environ.get("FAKE_OLGA_RESULTS") == "1":
        (Path.cwd() / (case.stem + ".tpl")).write_bytes(b"fake-tpl")
        (Path.cwd() / (case.stem + ".ppl")).write_bytes(b"fake-ppl")
    if os.environ.get("FAKE_OLGA_BATCH_FAIL") == "1":
        (Path.cwd() / "BatchExecutionSummary.txt").write_text(
            "0 of 1 case(s) finished successfully\n1 case(s) failed\n",
            encoding="utf-8",
        )
    print("FAKE-OLGA finished", flush=True)
    return int(os.environ.get("FAKE_OLGA_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
