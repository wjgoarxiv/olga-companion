"""
parametric_sweep.py — Parametric sweep runner for OLGA simulations.

Auto-generates N genkey variants from parameter ranges, runs sequentially,
and collects results.

Usage:
    python parametric_sweep.py base.genkey \\
        --sweep "INTEGRATION.ENDTIME=3600,7200" \\
        --sweep "PIPE.DIAMETER=0.1,0.2:Pipe_1" \\
        --strategy oat --max-cases 50 --output-dir _sweep/ [--dry-run] [--json]

Exit codes:
    0 — success
    1 — domain error (too many cases, validation failure, etc.)
    2 — I/O error
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from itertools import product
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path bootstrap
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from genkey_parser import GenkeyParser
from genkey_validator import GenkeyValidator


# ---------------------------------------------------------------------------
# Parameter string parser
# ---------------------------------------------------------------------------

def parse_sweep_spec(spec: str) -> dict:
    """Parse a CLI sweep spec string into a parameter dict.

    Format: KEYWORD.KEY=v1,v2,v3[:LABEL]

    Returns dict with keys: keyword, key, values, label (or None).
    Raises ValueError on malformed input.
    """
    if '=' not in spec:
        raise ValueError(f"Invalid sweep spec (missing '='): {spec!r}")

    left, right = spec.split('=', 1)

    # Parse KEYWORD.KEY
    if '.' not in left:
        raise ValueError(f"Invalid sweep spec (missing '.' in KEYWORD.KEY): {spec!r}")
    keyword, key = left.split('.', 1)
    keyword = keyword.strip().upper()
    key = key.strip().upper()

    # Parse values and optional :LABEL
    label = None
    if ':' in right:
        values_part, label = right.rsplit(':', 1)
        label = label.strip() or None
    else:
        values_part = right

    raw_values = [v.strip() for v in values_part.split(',')]
    if not raw_values or any(v == '' for v in raw_values):
        raise ValueError(f"Invalid sweep spec (empty values): {spec!r}")

    # Try to parse each value as float, fall back to str
    values = []
    for v in raw_values:
        try:
            values.append(float(v))
        except ValueError:
            values.append(v)

    return {'keyword': keyword, 'key': key, 'values': values, 'label': label}


# ---------------------------------------------------------------------------
# ParametricSweep
# ---------------------------------------------------------------------------

class ParametricSweep:
    """Generate and run parametric sweep cases for OLGA simulations."""

    def __init__(self, base_genkey: str, output_dir: str = '_sweep/'):
        self.base_genkey = str(Path(base_genkey).resolve())
        if not Path(self.base_genkey).exists():
            raise FileNotFoundError(f"Base genkey not found: {self.base_genkey}")
        self.output_dir = str(Path(output_dir))
        self._params = []   # list of dicts: {keyword, key, values, label}
        self._cases = []    # populated by generate()

    def add_parameter(self, keyword: str, key: str, values: list, label: str = None):
        """Add a sweep dimension.

        keyword='INTEGRATION', key='ENDTIME', values=[3600, 7200]
        """
        if not values:
            raise ValueError("values list must not be empty")
        self._params.append({
            'keyword': keyword.upper(),
            'key': key.upper(),
            'values': list(values),
            'label': label,
        })

    def generate(self, strategy: str = 'oat', max_cases: int = 50) -> list:
        """Generate genkey variants and return list of case dicts.

        strategy='oat': one-at-a-time — vary one parameter while holding
            others at their baseline (first) value.
            N = sum(len(v)-1 for each param) + 1 baseline

        strategy='cartesian': full Cartesian product.
            N = product(len(v) for each param)

        Raises ValueError if N > max_cases.
        Returns list of dicts: [{path, params, index}, ...]
        """
        if not self._params:
            raise ValueError("No parameters added. Call add_parameter() first.")

        strategy = strategy.lower()
        if strategy not in ('oat', 'cartesian'):
            raise ValueError(f"Unknown strategy {strategy!r}. Use 'oat' or 'cartesian'.")

        case_param_sets = self._build_case_param_sets(strategy)

        n = len(case_param_sets)
        if n > max_cases:
            raise ValueError(
                f"Sweep would generate {n} cases, exceeding max_cases={max_cases}. "
                f"Reduce parameter ranges or increase --max-cases."
            )

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        self._cases = []
        for i, param_set in enumerate(case_param_sets):
            case_dir = Path(self.output_dir) / f"case_{i:03d}"
            case_dir.mkdir(parents=True, exist_ok=True)

            base_name = Path(self.base_genkey).stem
            case_path = str(case_dir / f"case_{i:03d}.genkey")

            # Copy base genkey
            shutil.copy2(self.base_genkey, case_path)

            # Apply each parameter modification via genkey_writer.py
            validation_errors = []
            for param in param_set:
                cmd = [
                    sys.executable,
                    os.path.join(_SCRIPTS_DIR, 'genkey_writer.py'),
                    case_path,
                    param['keyword'],
                    param['key'],
                    str(param['value']),
                ]
                if param.get('label'):
                    cmd += ['--label', param['label']]
                try:
                    subprocess.run(cmd, check=True, capture_output=True)
                except subprocess.CalledProcessError as exc:
                    stderr = exc.stderr.decode('utf-8', errors='replace').strip()
                    validation_errors.append(
                        f"genkey_writer failed for {param['keyword']}.{param['key']}: {stderr}"
                    )

            # Validate
            try:
                parser = GenkeyParser(case_path)
                validator = GenkeyValidator(parser)
                findings = validator.validate()
                val_errors = [
                    f"[{f['rule_id']}] {f['message']}"
                    for f in findings
                    if f.get('severity') == 'ERROR'
                ]
                validation_errors.extend(val_errors)
            except Exception as exc:
                validation_errors.append(f"Validation exception: {exc}")

            self._cases.append({
                'index': i,
                'path': case_path,
                'params': param_set,
                'validation_errors': validation_errors,
                'valid': len(validation_errors) == 0,
            })

        return self._cases

    def run_all(self, dry_run: bool = False, timeout: int = None) -> list:
        """Run each generated case via olga_runner.

        If dry_run=True, skips actual execution and returns placeholder results.
        Returns list of result dicts.
        """
        if not self._cases:
            raise RuntimeError("No cases generated. Call generate() first.")

        results = []
        for case in self._cases:
            result = {
                'index': case['index'],
                'path': case['path'],
                'params': case['params'],
                'valid': case['valid'],
                'validation_errors': case['validation_errors'],
                'run_result': None,
            }

            if not case['valid']:
                print(
                    f"[sweep] Skipping case_{case['index']:03d}: "
                    f"{len(case['validation_errors'])} validation error(s)"
                )
                results.append(result)
                continue

            if dry_run:
                print(f"[sweep] DRY RUN case_{case['index']:03d}: {case['path']}")
                result['run_result'] = {'dry_run': True, 'success': None}
                results.append(result)
                continue

            print(f"[sweep] Running case_{case['index']:03d}: {case['path']}")

            cmd = [
                sys.executable,
                os.path.join(_SCRIPTS_DIR, 'olga_runner.py'),
                case['path'],
                '--output-dir', str(Path(case['path']).parent),
            ]
            if timeout is not None:
                cmd += ['--timeout', str(timeout)]

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=timeout,
                )
                result['run_result'] = {
                    'success': proc.returncode == 0,
                    'exit_code': proc.returncode,
                    'stdout': proc.stdout,
                    'stderr': proc.stderr,
                }
            except subprocess.TimeoutExpired:
                result['run_result'] = {
                    'success': False,
                    'exit_code': None,
                    'stdout': '',
                    'stderr': f'Timed out after {timeout}s',
                }
            except Exception as exc:
                result['run_result'] = {
                    'success': False,
                    'exit_code': None,
                    'stdout': '',
                    'stderr': str(exc),
                }

            status = "OK" if result['run_result']['success'] else "FAILED"
            print(f"[sweep] case_{case['index']:03d}: {status}")
            results.append(result)

        return results

    def summary_table(self, variables: list = None):
        """Print a comparison table: case | param values | result metrics."""
        if not self._cases:
            print("[sweep] No cases generated yet.")
            return

        # Build header
        param_headers = []
        for p in self._params:
            lbl = f"({p['label']})" if p.get('label') else ''
            param_headers.append(f"{p['keyword']}.{p['key']}{lbl}")

        col_widths = {
            'case': 10,
            'valid': 7,
        }
        for h in param_headers:
            col_widths[h] = max(len(h), 12)

        # Print header row
        header_parts = [
            'Case'.ljust(col_widths['case']),
            'Valid'.ljust(col_widths['valid']),
        ]
        for h in param_headers:
            header_parts.append(h.ljust(col_widths[h]))
        header_line = ' | '.join(header_parts)
        separator = '-' * len(header_line)

        print(separator)
        print(header_line)
        print(separator)

        for case in self._cases:
            row_parts = [
                f"case_{case['index']:03d}".ljust(col_widths['case']),
                ('OK' if case['valid'] else 'ERROR').ljust(col_widths['valid']),
            ]
            for i, p in enumerate(self._params):
                # Find this param's value in this case's param_set
                val = ''
                for cp in case['params']:
                    if cp['keyword'] == p['keyword'] and cp['key'] == p['key']:
                        v = cp['value']
                        val = f"{v:g}" if isinstance(v, float) else str(v)
                        break
                h = param_headers[i]
                row_parts.append(val.ljust(col_widths[h]))
            print(' | '.join(row_parts))

        print(separator)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_case_param_sets(self, strategy: str) -> list:
        """Build list of param_sets for each case.

        Each param_set is a list of dicts: {keyword, key, value, label}.
        """
        baselines = [
            {
                'keyword': p['keyword'],
                'key': p['key'],
                'value': p['values'][0],
                'label': p['label'],
            }
            for p in self._params
        ]

        if strategy == 'oat':
            case_param_sets = [list(baselines)]  # case_000 = all baselines

            for param_idx, p in enumerate(self._params):
                for value in p['values'][1:]:  # skip baseline (index 0)
                    param_set = list(baselines)  # copy baselines
                    param_set[param_idx] = {
                        'keyword': p['keyword'],
                        'key': p['key'],
                        'value': value,
                        'label': p['label'],
                    }
                    case_param_sets.append(param_set)

        else:  # cartesian
            value_lists = [p['values'] for p in self._params]
            case_param_sets = []
            for combo in product(*value_lists):
                param_set = [
                    {
                        'keyword': self._params[i]['keyword'],
                        'key': self._params[i]['key'],
                        'value': v,
                        'label': self._params[i]['label'],
                    }
                    for i, v in enumerate(combo)
                ]
                case_param_sets.append(param_set)

        return case_param_sets


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='parametric_sweep.py',
        description='Parametric sweep runner for OLGA simulations.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python parametric_sweep.py base.genkey --sweep "INTEGRATION.ENDTIME=3600,7200"
  python parametric_sweep.py base.genkey \\
      --sweep "INTEGRATION.ENDTIME=3600,7200" \\
      --sweep "PIPE.DIAMETER=0.1,0.2:Pipe_1" \\
      --strategy oat --max-cases 50 --dry-run
        """,
    )
    p.add_argument('base_genkey', help='Path to the base .genkey file')
    p.add_argument(
        '--sweep', metavar='SPEC', action='append', dest='sweeps', default=[],
        help='Sweep parameter spec: KEYWORD.KEY=v1,v2,v3[:LABEL] (repeatable)',
    )
    p.add_argument(
        '--strategy', choices=['oat', 'cartesian'], default='oat',
        help='Sweep strategy: oat=one-at-a-time (default), cartesian=full product',
    )
    p.add_argument(
        '--max-cases', type=int, default=50, metavar='N',
        help='Maximum number of cases allowed (default: 50)',
    )
    p.add_argument(
        '--output-dir', default='_sweep/', metavar='DIR',
        help='Directory for generated cases (default: _sweep/)',
    )
    p.add_argument(
        '--dry-run', action='store_true',
        help='Generate cases but skip OLGA execution',
    )
    p.add_argument(
        '--timeout', type=int, default=None, metavar='SECS',
        help='Per-case OLGA timeout in seconds',
    )
    p.add_argument(
        '--json', action='store_true',
        help='Print results as JSON to stdout',
    )
    return p


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if not args.sweeps:
        parser.error("at least one --sweep spec is required")

    # Resolve base genkey
    base_path = Path(args.base_genkey)
    if not base_path.exists():
        print(f"Error: base genkey not found: {args.base_genkey}", file=sys.stderr)
        sys.exit(2)

    # Parse sweep specs
    try:
        sweep = ParametricSweep(str(base_path), output_dir=args.output_dir)
        for spec in args.sweeps:
            param = parse_sweep_spec(spec)
            sweep.add_parameter(
                keyword=param['keyword'],
                key=param['key'],
                values=param['values'],
                label=param['label'],
            )
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"I/O error: {exc}", file=sys.stderr)
        sys.exit(2)

    # Generate cases
    try:
        cases = sweep.generate(strategy=args.strategy, max_cases=args.max_cases)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"I/O error: {exc}", file=sys.stderr)
        sys.exit(2)

    print(f"[sweep] Generated {len(cases)} case(s) in {args.output_dir}")

    # Run all cases
    try:
        results = sweep.run_all(dry_run=args.dry_run, timeout=args.timeout)
    except OSError as exc:
        print(f"I/O error: {exc}", file=sys.stderr)
        sys.exit(2)

    # Output
    if args.json:
        # Produce JSON-safe output
        output = []
        for r in results:
            entry = {
                'index': r['index'],
                'path': r['path'],
                'valid': r['valid'],
                'validation_errors': r['validation_errors'],
                'params': [
                    {
                        'keyword': p['keyword'],
                        'key': p['key'],
                        'value': p['value'],
                        'label': p['label'],
                    }
                    for p in r['params']
                ],
                'run_result': r['run_result'],
            }
            output.append(entry)
        print(json.dumps(output, indent=2, ensure_ascii=True))
    else:
        sweep.summary_table()

    # Exit with failure if any run failed
    failed = [
        r for r in results
        if r.get('run_result') and r['run_result'].get('success') is False
    ]
    if failed and not args.dry_run:
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
