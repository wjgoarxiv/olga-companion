"""
run_monitor.py -- Live progress monitor for OLGA .out file (Stage 3, experimental).

Tails the .out file produced during an active OLGA simulation and prints
real-time progress updates derived from the timestep lines OLGA writes.

Usage:
    python run_monitor.py case.out [--interval 5] [--timeout 3600]

Exit codes:
    0 -- monitoring completed (timeout reached or file closed cleanly)
    1 -- domain error (bad arguments, pattern not found, etc.)
    2 -- I/O error (file unreadable, etc.)

Note: This is experimental. The .out file must already be growing (OLGA
running). For testing, create a mock by appending lines to a temp file.
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# sys.path bootstrap
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# RunMonitor
# ---------------------------------------------------------------------------

# Pattern: --*++*-- Time: Xs. Step no: N/M
_PROGRESS_RE = re.compile(
    r'--\*\+\+\*--\s+Time:\s*([\d.]+)s\.\s+Step no:\s*(\d+)/(\d+)'
)

# Optional: OLGA also emits dt on the same or nearby line
# e.g. "DT= 0.50000E+00"
_DT_RE = re.compile(r'DT=\s*([\d.Ee+\-]+)')


class RunMonitor:
    """
    Live tail-and-parse monitor for an OLGA .out file.

    Parameters
    ----------
    out_path : str
        Path to the .out file (may not exist yet when the monitor starts).
    """

    def __init__(self, out_path: str):
        self.out_path = str(Path(out_path))

    # ------------------------------------------------------------------
    # Generator: tail
    # ------------------------------------------------------------------

    def tail(self, interval: float = 2, max_lines: int = 50):
        """
        Generator that yields new lines from the .out file.

        Waits up to ``interval`` seconds between polls. Yields up to
        ``max_lines`` new lines per poll cycle. Tracks seek position so
        already-seen content is never re-emitted.

        Parameters
        ----------
        interval : float
            Polling interval in seconds (default 2).
        max_lines : int
            Maximum lines to yield per poll cycle (default 50).

        Yields
        ------
        str
            Each new line (newline stripped).
        """
        seek_pos = 0

        while True:
            if not Path(self.out_path).exists():
                time.sleep(interval)
                continue

            try:
                with open(self.out_path, 'r', encoding='cp949', errors='replace') as fh:
                    fh.seek(seek_pos)
                    lines_this_cycle = 0
                    for raw in fh:
                        yield raw.rstrip('\n').rstrip('\r')
                        lines_this_cycle += 1
                        if lines_this_cycle >= max_lines:
                            break
                    seek_pos = fh.tell()
            except OSError:
                pass

            time.sleep(interval)

    # ------------------------------------------------------------------
    # parse_progress
    # ------------------------------------------------------------------

    def parse_progress(self, line: str):
        """
        Extract timestep info from an OLGA progress line.

        Matches: ``--*++*-- Time: Xs. Step no: N/M``

        Also attempts to extract DT from the same line.

        Parameters
        ----------
        line : str
            A single line from the .out file.

        Returns
        -------
        dict or None
            Keys: time (float, s), step (int), total (int),
                  dt (float or None), progress_pct (float 0-100).
            Returns None if the line does not match.
        """
        m = _PROGRESS_RE.search(line)
        if not m:
            return None

        sim_time = float(m.group(1))
        step = int(m.group(2))
        total = int(m.group(3))

        dt = None
        m_dt = _DT_RE.search(line)
        if m_dt:
            try:
                dt = float(m_dt.group(1))
            except ValueError:
                dt = None

        progress_pct = (step / total * 100.0) if total > 0 else 0.0

        return {
            'time': sim_time,
            'step': step,
            'total': total,
            'dt': dt,
            'progress_pct': progress_pct,
        }

    # ------------------------------------------------------------------
    # estimate_remaining
    # ------------------------------------------------------------------

    def estimate_remaining(
        self,
        current_time: float,
        current_step: int,
        total_steps: int,
        elapsed_wall: float,
    ) -> float | None:
        """
        Linear ETA estimation in wall-clock seconds.

        Parameters
        ----------
        current_time : float
            Current simulation time (seconds, unused -- kept for API completeness).
        current_step : int
            Current step number.
        total_steps : int
            Total steps expected.
        elapsed_wall : float
            Wall-clock seconds elapsed so far.

        Returns
        -------
        float or None
            Estimated remaining wall-clock seconds, or None if not computable.
        """
        if current_step <= 0 or total_steps <= 0 or elapsed_wall <= 0:
            return None
        rate = current_step / elapsed_wall          # steps per wall second
        remaining_steps = total_steps - current_step
        if rate <= 0:
            return None
        return remaining_steps / rate

    # ------------------------------------------------------------------
    # monitor (blocking)
    # ------------------------------------------------------------------

    def monitor(self, timeout: float = None):
        """
        Blocking loop: tail .out file, parse progress lines, print updates.

        Output format example::

            [12.5%] t=10800s dt=0.5s step 1350000/10800000  ETA 3600s

        Parameters
        ----------
        timeout : float or None
            Stop after this many wall-clock seconds. None = run forever
            (until KeyboardInterrupt).
        """
        print('[run_monitor] Watching: %s' % self.out_path)
        if timeout:
            print('[run_monitor] Timeout: %ss' % timeout)

        start_wall = time.monotonic()
        last_progress = None

        try:
            for line in self.tail(interval=2):
                elapsed = time.monotonic() - start_wall
                if timeout and elapsed >= timeout:
                    print('\n[run_monitor] Timeout reached (%.0fs).' % elapsed)
                    break

                info = self.parse_progress(line)
                if info is None:
                    continue

                # Avoid printing identical steps twice
                if last_progress and last_progress['step'] == info['step']:
                    continue
                last_progress = info

                dt_str = ('dt=%.4gs' % info['dt']) if info['dt'] is not None else 'dt=?'
                eta = self.estimate_remaining(
                    info['time'], info['step'], info['total'], elapsed
                )
                eta_str = ('  ETA %.0fs' % eta) if eta is not None else ''

                print('[%5.1f%%] t=%.4gs %s step %d/%d%s' % (
                    info['progress_pct'],
                    info['time'],
                    dt_str,
                    info['step'],
                    info['total'],
                    eta_str,
                ))

        except KeyboardInterrupt:
            print('\n[run_monitor] Interrupted by user.')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='run_monitor.py',
        description='Live progress monitor for an OLGA .out file (experimental).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_monitor.py case.out
  python run_monitor.py case.out --interval 5 --timeout 3600
        """,
    )
    p.add_argument('out_file', help='Path to the OLGA .out file to monitor')
    p.add_argument(
        '--interval', type=float, default=2, metavar='SECS',
        help='Polling interval in seconds (default: 2)',
    )
    p.add_argument(
        '--timeout', type=float, default=None, metavar='SECS',
        help='Stop monitoring after this many seconds (default: run until Ctrl-C)',
    )
    return p


def main():
    parser = _build_parser()
    args = parser.parse_args()

    try:
        monitor = RunMonitor(args.out_file)
    except Exception as exc:
        print('Error: %s' % exc, file=sys.stderr)
        sys.exit(1)

    monitor.monitor(timeout=args.timeout)
    sys.exit(0)


if __name__ == '__main__':
    main()
