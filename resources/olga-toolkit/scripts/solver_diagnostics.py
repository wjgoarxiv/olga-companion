"""
solver_diagnostics.py -- Parse OLGA .out log files for convergence diagnostics,
issue detection, and fix suggestions.

Usage:
    python solver_diagnostics.py case.out
    python solver_diagnostics.py case.out --json
    python solver_diagnostics.py case.out --plot convergence.png
    python solver_diagnostics.py case.out --issues-only

Exit codes:
    0 = no issues detected
    1 = issues found
    2 = parse error
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_TIMESTEP = re.compile(
    r'--\*\+\+\*--\s+Time:\s+(\S+)s\.\s+Step no:\s+(\d+)/(\d+)\.'
    r'\s+Current step-size:\s+(\S+)s'
)
_RE_CPU = re.compile(
    r'TOTAL CPU USAGE:\s+(\d+)\s+%'
)
_RE_MASS_ERROR_HEADER = re.compile(
    r'^Mass error information:\s*$'
)
_RE_MASS_ERROR_VALUE = re.compile(
    r'([A-Za-z][A-Za-z0-9_ ]*?)\s*[=:]\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)',
    re.IGNORECASE
)
_RE_DTMIN = re.compile(r'DTMIN|minimum\s+timestep', re.IGNORECASE)
_RE_NEG_HOLDUP = re.compile(r'negative.*holdup|holdup.*negative', re.IGNORECASE)
_RE_NAN_INF = re.compile(r'\bNaN\b|\bInf\b', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_float(s):
    """Parse a float string, including scientific notation."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _read_out(path):
    """Read .out file with utf-8, falling back char-by-char on errors."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return lines
    except OSError as exc:
        raise IOError("Cannot open file: {}".format(exc)) from exc


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class SolverDiagnostics:
    """Parse and diagnose an OLGA .out log file."""

    def __init__(self, out_path):
        """Read and parse .out file."""
        self.path = Path(out_path)
        self._lines = _read_out(str(self.path))
        # Cache parsed results lazily
        self._timesteps = None
        self._mass_errors = None
        self._cpu_usage = None
        self._issues = None

    # -----------------------------------------------------------------------
    # Public parse methods
    # -----------------------------------------------------------------------

    def parse_timesteps(self):
        """Extract timestep progression.

        Returns list of dicts: [{time, step_no, total_steps, step_size}, ...]
        """
        if self._timesteps is not None:
            return self._timesteps

        result = []
        for line in self._lines:
            m = _RE_TIMESTEP.search(line)
            if m:
                time = _parse_float(m.group(1))
                step_no = int(m.group(2))
                total_steps = int(m.group(3))
                step_size = _parse_float(m.group(4))
                if time is not None and step_size is not None:
                    result.append({
                        'time': time,
                        'step_no': step_no,
                        'total_steps': total_steps,
                        'step_size': step_size,
                    })

        self._timesteps = result
        return result

    def parse_mass_errors(self):
        """Extract mass balance error information.

        Returns list of dicts with timestep and error values.
        Each dict: {time, flowpath, errors: {name: value}}
        """
        if self._mass_errors is not None:
            return self._mass_errors

        result = []
        timesteps = self.parse_timesteps()

        # Build a quick index: line_no -> timestep entry
        ts_by_line = {}
        for line_idx, line in enumerate(self._lines):
            m = _RE_TIMESTEP.search(line)
            if m:
                time = _parse_float(m.group(1))
                ts_by_line[line_idx] = time

        current_time = None
        current_flowpath = None
        in_mass_block = False
        block_errors = {}

        def flush_block():
            if block_errors and current_time is not None:
                result.append({
                    'time': current_time,
                    'flowpath': current_flowpath,
                    'errors': dict(block_errors),
                })

        for i, line in enumerate(self._lines):
            stripped = line.strip()

            # Track current time from timestep markers
            if i in ts_by_line:
                current_time = ts_by_line[i]
                in_mass_block = False
                current_flowpath = None
                block_errors = {}

            # Track current flowpath
            if stripped.startswith('Variables for FlowPath:'):
                flush_block()
                current_flowpath = stripped.split('Variables for FlowPath:', 1)[-1].strip()
                in_mass_block = False
                block_errors = {}

            # Detect mass error header
            if _RE_MASS_ERROR_HEADER.match(stripped):
                flush_block()
                in_mass_block = True
                block_errors = {}
                continue

            # Collect values inside mass error block
            if in_mass_block:
                # A non-empty line with key=value pairs
                if stripped and not stripped.startswith('--') and not stripped.startswith('*'):
                    for m in _RE_MASS_ERROR_VALUE.finditer(stripped):
                        key = m.group(1).strip()
                        val = _parse_float(m.group(2))
                        if val is not None:
                            block_errors[key] = val
                # Blank line ends the block; flush only if values were found
                elif not stripped:
                    flush_block()
                    in_mass_block = False
                    block_errors = {}

        # Flush any trailing block
        flush_block()

        self._mass_errors = result
        return result

    def parse_cpu_usage(self):
        """Extract CPU usage entries.

        Returns list of {time, cpu_pct}.
        The CPU summary appears once at end-of-run; time is set to final sim time.
        """
        if self._cpu_usage is not None:
            return self._cpu_usage

        result = []
        timesteps = self.parse_timesteps()
        final_time = timesteps[-1]['time'] if timesteps else None

        for line in self._lines:
            m = _RE_CPU.search(line)
            if m:
                cpu_pct = int(m.group(1))
                result.append({
                    'time': final_time,
                    'cpu_pct': cpu_pct,
                })

        self._cpu_usage = result
        return result

    # -----------------------------------------------------------------------
    # Issue detection
    # -----------------------------------------------------------------------

    def detect_issues(self):
        """Scan for problems.

        Returns list of issue dicts:
        [{type, severity, time, message, line_no}, ...]

        Issue types: DTMIN_HIT, NEGATIVE_HOLDUP, NAN_VALUE, STALLED, MASS_ERROR
        Severity: ERROR, WARNING, INFO
        """
        if self._issues is not None:
            return self._issues

        issues = []
        timesteps = self.parse_timesteps()

        # --- Per-line scanning for DTMIN, negative holdup, NaN/Inf ---
        # Track current sim time by scanning timestep markers line by line
        current_time = None
        for line_no, line in enumerate(self._lines, start=1):
            ts_m = _RE_TIMESTEP.search(line)
            if ts_m:
                current_time = _parse_float(ts_m.group(1))
                continue

            if _RE_DTMIN.search(line):
                issues.append({
                    'type': 'DTMIN_HIT',
                    'severity': 'WARNING',
                    'time': current_time,
                    'message': 'DTMIN hit: ' + line.strip(),
                    'line_no': line_no,
                })

            if _RE_NEG_HOLDUP.search(line):
                issues.append({
                    'type': 'NEGATIVE_HOLDUP',
                    'severity': 'ERROR',
                    'time': current_time,
                    'message': 'Negative holdup: ' + line.strip(),
                    'line_no': line_no,
                })

            if _RE_NAN_INF.search(line):
                issues.append({
                    'type': 'NAN_VALUE',
                    'severity': 'ERROR',
                    'time': current_time,
                    'message': 'NaN/Inf detected: ' + line.strip(),
                    'line_no': line_no,
                })

        # --- STALLED: no meaningful time progress between consecutive records ---
        if len(timesteps) >= 2:
            for i in range(1, len(timesteps)):
                prev = timesteps[i - 1]
                curr = timesteps[i]
                # If reported time hasn't advanced but step count has
                if curr['time'] <= prev['time'] and curr['step_no'] > prev['step_no']:
                    issues.append({
                        'type': 'STALLED',
                        'severity': 'WARNING',
                        'time': curr['time'],
                        'message': (
                            'Simulation time stalled at {:.3e}s between '
                            'step {} and {}'.format(
                                curr['time'], prev['step_no'], curr['step_no']
                            )
                        ),
                        'line_no': None,
                    })

        # --- MASS_ERROR: look for suspiciously large error values ---
        mass_errors = self.parse_mass_errors()
        _MASS_THRESH = 1e-3  # relative threshold: flag anything >= 0.1%
        for entry in mass_errors:
            for name, val in entry.get('errors', {}).items():
                if abs(val) >= _MASS_THRESH:
                    issues.append({
                        'type': 'MASS_ERROR',
                        'severity': 'WARNING',
                        'time': entry.get('time'),
                        'message': (
                            'Large mass error in {} [{}]: {:.3e}'.format(
                                entry.get('flowpath', 'unknown'), name, val
                            )
                        ),
                        'line_no': None,
                    })

        # Sort by time (None times go last)
        issues.sort(key=lambda x: (x['time'] is None, x['time'] or 0))

        self._issues = issues
        return issues

    # -----------------------------------------------------------------------
    # Multi-run comparison
    # -----------------------------------------------------------------------

    @classmethod
    def compare_runs(cls, out_paths):
        """Parse multiple .out files and return a comparison table.

        Parameters
        ----------
        out_paths : list of str or Path
            Paths to .out log files.

        Returns
        -------
        list of dicts, one per file:
            {path, n_timesteps, min_dt, max_dt, n_dtmin_hits, cpu_pct, n_issues}
        """
        rows = []
        for p in out_paths:
            try:
                diag = cls(p)
                timesteps = diag.parse_timesteps()
                cpu_list = diag.parse_cpu_usage()
                issues = diag.detect_issues()

                n_dtmin = sum(1 for iss in issues if iss['type'] == 'DTMIN_HIT')
                cpu_pct = cpu_list[-1]['cpu_pct'] if cpu_list else None

                if timesteps:
                    min_dt = min(t['step_size'] for t in timesteps)
                    max_dt = max(t['step_size'] for t in timesteps)
                else:
                    min_dt = None
                    max_dt = None

                rows.append({
                    'path': str(p),
                    'n_timesteps': len(timesteps),
                    'min_dt': min_dt,
                    'max_dt': max_dt,
                    'n_dtmin_hits': n_dtmin,
                    'cpu_pct': cpu_pct,
                    'n_issues': len(issues),
                })
            except (IOError, Exception) as exc:
                rows.append({
                    'path': str(p),
                    'n_timesteps': None,
                    'min_dt': None,
                    'max_dt': None,
                    'n_dtmin_hits': None,
                    'cpu_pct': None,
                    'n_issues': None,
                    'error': str(exc),
                })
        return rows

    # -----------------------------------------------------------------------
    # Flowpath attribution
    # -----------------------------------------------------------------------

    def flowpath_attribution(self):
        """Group mass errors by flowpath.

        Scans "Variables for FlowPath: X" headers and the mass error blocks
        that follow them to count and bound errors per flowpath.

        Returns
        -------
        dict: {flowpath_name: {'n_mass_errors': int, 'max_error': float}}
        """
        mass_errors = self.parse_mass_errors()
        result = {}
        for entry in mass_errors:
            fp = entry.get('flowpath') or 'unknown'
            errors = entry.get('errors', {})
            for val in errors.values():
                if fp not in result:
                    result[fp] = {'n_mass_errors': 0, 'max_error': 0.0}
                result[fp]['n_mass_errors'] += 1
                if abs(val) > result[fp]['max_error']:
                    result[fp]['max_error'] = abs(val)
        return result

    # -----------------------------------------------------------------------
    # Fix suggestions
    # -----------------------------------------------------------------------

    def suggest_fixes(self):
        """Based on detected issues, suggest parameter changes.

        Returns list of suggestion strings.
        """
        issues = self.detect_issues()
        types_seen = {iss['type'] for iss in issues}
        suggestions = []

        if 'DTMIN_HIT' in types_seen:
            suggestions.append(
                'DTMIN_HIT: Increase INTEGRATION MINDT or decrease MAXDT '
                'to avoid timestep oscillation.'
            )
        if 'NEGATIVE_HOLDUP' in types_seen:
            suggestions.append(
                'NEGATIVE_HOLDUP: Check boundary conditions; consider adding '
                'initial condition ramping to avoid sharp transients.'
            )
        if 'NAN_VALUE' in types_seen:
            suggestions.append(
                'NAN_VALUE: Reduce INTEGRATION DTSTART; check for extreme '
                'boundary conditions or flash discontinuities.'
            )
        if 'STALLED' in types_seen:
            suggestions.append(
                'STALLED: Increase INTEGRATION MAXDT; check for conflicting '
                'constraints that prevent time advancement.'
            )
        if 'MASS_ERROR' in types_seen:
            suggestions.append(
                'MASS_ERROR: Tighten mass tolerance (MASSTOL); reduce timestep '
                'range (MINDT/MAXDT) to improve balance convergence.'
            )

        return suggestions

    # -----------------------------------------------------------------------
    # Convergence plot
    # -----------------------------------------------------------------------

    def convergence_plot(self, output=None):
        """Plot timestep size vs simulation time. Save PNG if output given."""
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
        except ImportError:
            print('matplotlib not available; skipping plot.', file=sys.stderr)
            return

        timesteps = self.parse_timesteps()
        if not timesteps:
            print('No timestep data found; skipping plot.', file=sys.stderr)
            return

        times = [t['time'] for t in timesteps]
        sizes = [t['step_size'] for t in timesteps]

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.semilogy(times, sizes, linewidth=0.8, color='steelblue')
        ax.set_xlabel('Simulation Time (s)')
        ax.set_ylabel('Step Size (s)')
        ax.set_title('OLGA Solver Convergence: {}'.format(self.path.name))
        ax.grid(True, which='both', linestyle='--', alpha=0.5)

        # Mark issue times
        issues = self.detect_issues()
        issue_times = [iss['time'] for iss in issues if iss['time'] is not None]
        if issue_times:
            # Find step sizes at issue times (nearest match)
            time_set = {t: s for t, s in zip(times, sizes)}
            for it in set(issue_times):
                nearest_t = min(times, key=lambda t: abs(t - it))
                ax.axvline(x=nearest_t, color='red', alpha=0.4, linewidth=0.8)

        plt.tight_layout()
        dest = output or str(self.path.with_suffix('.png'))
        plt.savefig(dest, dpi=150)
        plt.close(fig)
        print('Plot saved: {}'.format(dest))

    # -----------------------------------------------------------------------
    # Summary report
    # -----------------------------------------------------------------------

    def summary(self):
        """Human-readable summary report."""
        timesteps = self.parse_timesteps()
        cpu_list = self.parse_cpu_usage()
        issues = self.detect_issues()
        suggestions = self.suggest_fixes()

        lines = []
        lines.append('=' * 60)
        lines.append('OLGA Solver Diagnostics: {}'.format(self.path.name))
        lines.append('=' * 60)

        # Timestep summary
        if timesteps:
            t_first = timesteps[0]
            t_last = timesteps[-1]
            dt_min = min(t['step_size'] for t in timesteps)
            dt_max = max(t['step_size'] for t in timesteps)
            lines.append('')
            lines.append('Timestep summary:')
            lines.append('  Records     : {}'.format(len(timesteps)))
            lines.append('  Time range  : {:.3e}s -- {:.3e}s'.format(
                t_first['time'], t_last['time']))
            lines.append('  Step range  : {} -- {}'.format(
                t_first['step_no'], t_last['step_no']))
            lines.append('  Step size   : min={:.3e}s  max={:.3e}s'.format(
                dt_min, dt_max))
        else:
            lines.append('')
            lines.append('Timestep summary: no timestep records found.')

        # CPU
        if cpu_list:
            lines.append('')
            lines.append('CPU usage:')
            for entry in cpu_list:
                lines.append('  {}%'.format(entry['cpu_pct']))

        # Issues
        lines.append('')
        if issues:
            lines.append('Issues detected ({} total):'.format(len(issues)))
            for iss in issues:
                t_str = '{:.3e}s'.format(iss['time']) if iss['time'] is not None else 'N/A'
                ln_str = ' (line {})'.format(iss['line_no']) if iss['line_no'] else ''
                lines.append('  [{}] {} @ {}{}: {}'.format(
                    iss['severity'], iss['type'], t_str, ln_str, iss['message']
                ))
        else:
            lines.append('No issues detected.')

        # Suggestions
        if suggestions:
            lines.append('')
            lines.append('Suggested fixes:')
            for s in suggestions:
                lines.append('  - ' + s)

        lines.append('')
        return '\n'.join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    p = argparse.ArgumentParser(
        description='Parse OLGA .out log files for convergence diagnostics.'
    )
    p.add_argument('out_file', help='Path to the OLGA .out log file')
    p.add_argument('--json', action='store_true',
                   help='Output results as JSON')
    p.add_argument('--plot', metavar='FILE',
                   help='Save convergence plot to FILE (PNG). Requires matplotlib.')
    p.add_argument('--issues-only', action='store_true',
                   help='Print only detected issues')
    return p


def main():
    # Windows cp949 safety: reconfigure stdout to utf-8
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    parser = _build_parser()
    args = parser.parse_args()

    out_path = args.out_file
    if not os.path.isfile(out_path):
        print('Error: file not found: {}'.format(out_path), file=sys.stderr)
        sys.exit(2)

    try:
        diag = SolverDiagnostics(out_path)
    except IOError as exc:
        print('Parse error: {}'.format(exc), file=sys.stderr)
        sys.exit(2)

    try:
        if args.plot:
            diag.convergence_plot(output=args.plot)

        if args.json:
            payload = {
                'file': str(diag.path),
                'timesteps': diag.parse_timesteps(),
                'cpu_usage': diag.parse_cpu_usage(),
                'issues': diag.detect_issues(),
                'suggestions': diag.suggest_fixes(),
            }
            print(json.dumps(payload, indent=2))
        elif args.issues_only:
            issues = diag.detect_issues()
            if not issues:
                print('No issues detected.')
            else:
                for iss in issues:
                    t_str = '{:.3e}s'.format(iss['time']) if iss['time'] is not None else 'N/A'
                    ln_str = ' (line {})'.format(iss['line_no']) if iss['line_no'] else ''
                    print('[{}] {} @ {}{}: {}'.format(
                        iss['severity'], iss['type'], t_str, ln_str, iss['message']
                    ))
        else:
            print(diag.summary())

    except Exception as exc:
        print('Error during analysis: {}'.format(exc), file=sys.stderr)
        sys.exit(2)

    issues = diag.detect_issues()
    sys.exit(1 if issues else 0)


if __name__ == '__main__':
    main()
