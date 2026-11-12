"""
iteration_helper.py -- Manual iteration assistant for parametric sweep results.

Ranks sweep results by a metric variable and suggests refined parameter ranges
for the next iteration, helping converge toward an optimal operating point.

Usage:
    python iteration_helper.py _sweep/ --metric LIQC --branch RETURN [--minimize] [--top 3]
    python iteration_helper.py _sweep/ --metric PT --branch INLET --maximize --suggest
    python iteration_helper.py _sweep/ --metric LIQC --branch RETURN --json
    python iteration_helper.py --history _sweep1/ _sweep2/ _sweep3/ --metric LIQC --branch RETURN

Exit codes:
    0 -- success
    1 -- domain error (no results found, metric not available, etc.)
    2 -- I/O error
"""

import argparse
import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# sys.path bootstrap
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from fast_plotter import FastTPLPlotter


# ---------------------------------------------------------------------------
# IterationHelper
# ---------------------------------------------------------------------------

class IterationHelper:
    """
    Rank sweep results and suggest refined parameter ranges for the next
    iteration.

    Parameters
    ----------
    sweep_dir : str
        Path to a parametric_sweep output directory (contains case_NNN/ subdirs).
    """

    def __init__(self, sweep_dir: str):
        self.sweep_dir = str(Path(sweep_dir))
        if not Path(self.sweep_dir).is_dir():
            raise FileNotFoundError('Sweep directory not found: %s' % self.sweep_dir)

        # Optionally read sweep config if parametric_sweep metadata exists
        self._sweep_config = self._try_load_sweep_config()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_load_sweep_config(self) -> dict:
        """Attempt to load sweep_config.json if present in sweep_dir."""
        cfg_path = Path(self.sweep_dir) / 'sweep_config.json'
        if cfg_path.exists():
            try:
                with open(str(cfg_path), 'r', encoding='utf-8', errors='replace') as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {}

    def _find_case_dirs(self) -> list:
        """Return sorted list of case_NNN subdirectory paths."""
        base = Path(self.sweep_dir)
        dirs = sorted(
            d for d in base.iterdir()
            if d.is_dir() and d.name.startswith('case_')
        )
        return [str(d) for d in dirs]

    def _find_tpl(self, case_dir: str) -> str | None:
        """Return path to the first .tpl file in a case directory, or None."""
        for fp in sorted(Path(case_dir).glob('*.tpl')):
            return str(fp)
        return None

    def _read_case_params(self, case_dir: str) -> dict:
        """
        Read params from case_params.json if present, else infer from dirname.

        Returns dict of {param_label: value}.
        """
        params_path = Path(case_dir) / 'case_params.json'
        if params_path.exists():
            try:
                with open(str(params_path), 'r', encoding='utf-8', errors='replace') as fh:
                    return json.load(fh)
            except Exception:
                pass
        # Fallback: return case directory name as only info
        return {'case': Path(case_dir).name}

    def _extract_final_value(
        self,
        tpl_path: str,
        metric_var: str,
        branch: str | None,
    ) -> float | None:
        """
        Extract the final (last time point) value of metric_var from a .tpl.

        Parameters
        ----------
        tpl_path : str
            Path to OLGA .tpl file.
        metric_var : str
            Variable name (e.g. 'LIQC', 'PT').
        branch : str or None
            Branch name filter. If None, uses the first available branch.

        Returns
        -------
        float or None
        """
        try:
            wanted_b = {branch} if branch else None
            wanted_v = {metric_var}
            plotter = FastTPLPlotter(
                tpl_path,
                max_pts=10,          # we only need the final value; keep it lean
                wanted_branches=wanted_b,
                wanted_vars=wanted_v,
            )

            # Resolve branch: use provided or pick first available
            if branch:
                use_branch = branch
            else:
                available = plotter.available_branches(metric_var)
                if not available:
                    return None
                use_branch = available[0]

            t, v = plotter.get(metric_var, use_branch)
            if v is None or len(v) == 0:
                return None
            return float(v[-1])
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_results(self, metric_var: str, branch: str = None) -> list:
        """
        For each case subdir, find .tpl and extract final value of metric_var.

        Parameters
        ----------
        metric_var : str
            OLGA variable to extract (e.g. 'LIQC', 'PT').
        branch : str or None
            Branch name filter.

        Returns
        -------
        list of dict
            Each entry: {case_path, params, metric_value (float or None)}.
        """
        results = []
        for case_dir in self._find_case_dirs():
            tpl = self._find_tpl(case_dir)
            params = self._read_case_params(case_dir)
            metric_value = None
            if tpl:
                metric_value = self._extract_final_value(tpl, metric_var, branch)
            results.append({
                'case_path': case_dir,
                'params': params,
                'metric_value': metric_value,
            })
        return results

    def rank_cases(
        self,
        metric_var: str,
        branch: str = None,
        minimize: bool = True,
    ) -> list:
        """
        Sort cases by metric value.

        Cases with metric_value=None are placed last.

        Parameters
        ----------
        metric_var : str
            Variable name to rank by.
        branch : str or None
            Branch filter.
        minimize : bool
            True = lowest metric first (default). False = highest first.

        Returns
        -------
        list of dict
            Ranked entries with added key 'rank' (1-based).
        """
        results = self.load_results(metric_var, branch)

        # Separate valid and invalid entries
        valid = [r for r in results if r['metric_value'] is not None]
        invalid = [r for r in results if r['metric_value'] is None]

        valid.sort(key=lambda r: r['metric_value'], reverse=not minimize)

        ranked = []
        for i, r in enumerate(valid):
            entry = dict(r)
            entry['rank'] = i + 1
            ranked.append(entry)
        for r in invalid:
            entry = dict(r)
            entry['rank'] = None
            ranked.append(entry)

        return ranked

    def suggest_refinement(
        self,
        metric_var: str,
        branch: str = None,
        minimize: bool = True,
        top_n: int = 3,
    ) -> dict:
        """
        Take top-N cases, compute narrowed parameter ranges for next iteration.

        The suggested range for each numeric parameter is:
            [min(top_n_values) * (1 - margin), max(top_n_values) * (1 + margin)]
        with a margin of 10%.

        Parameters
        ----------
        metric_var : str
            Variable to optimize.
        branch : str or None
            Branch filter.
        minimize : bool
            True = minimizing metric (default).
        top_n : int
            Number of top cases to use for range estimation.

        Returns
        -------
        dict
            Keys are parameter names, values are {'min': float, 'max': float,
            'suggested_values': [min, mid, max]}.
            Non-numeric parameters: {'values': [unique values in top_n]}.
        """
        ranked = self.rank_cases(metric_var, branch, minimize)
        top = [r for r in ranked if r['rank'] is not None][:top_n]

        if not top:
            return {}

        # Collect all param keys from top cases
        all_keys = set()
        for r in top:
            all_keys.update(r['params'].keys())

        suggestions = {}
        margin = 0.10  # 10%

        for key in sorted(all_keys):
            raw_values = []
            for r in top:
                v = r['params'].get(key)
                if v is not None:
                    raw_values.append(v)

            if not raw_values:
                continue

            # Try numeric
            try:
                nums = [float(v) for v in raw_values]
                lo = min(nums)
                hi = max(nums)
                lo_suggested = lo * (1 - margin) if lo >= 0 else lo * (1 + margin)
                hi_suggested = hi * (1 + margin) if hi >= 0 else hi * (1 - margin)
                mid = (lo_suggested + hi_suggested) / 2.0
                suggestions[key] = {
                    'min': round(lo_suggested, 6),
                    'max': round(hi_suggested, 6),
                    'suggested_values': [
                        round(lo_suggested, 6),
                        round(mid, 6),
                        round(hi_suggested, 6),
                    ],
                }
            except (ValueError, TypeError):
                # Non-numeric: list unique values
                seen = []
                for v in raw_values:
                    if v not in seen:
                        seen.append(v)
                suggestions[key] = {'values': seen}

        return suggestions

    def history(self, sweep_dirs: list, metric_var: str, branch: str = None) -> list:
        """
        Track how the best metric improved across multiple sweep iterations.

        Parameters
        ----------
        sweep_dirs : list of str
            Ordered list of sweep output directories (iteration 1, 2, ...).
        metric_var : str
            Variable to track.
        branch : str or None
            Branch filter.

        Returns
        -------
        list of dict
            Each entry: {iteration (1-based), sweep_dir, best_value, params}.
        """
        history_records = []
        for i, sweep_dir in enumerate(sweep_dirs):
            try:
                helper = IterationHelper(sweep_dir)
                ranked = helper.rank_cases(metric_var, branch, minimize=True)
                best = next((r for r in ranked if r['rank'] == 1), None)
                history_records.append({
                    'iteration': i + 1,
                    'sweep_dir': sweep_dir,
                    'best_value': best['metric_value'] if best else None,
                    'params': best['params'] if best else {},
                })
            except Exception as exc:
                history_records.append({
                    'iteration': i + 1,
                    'sweep_dir': sweep_dir,
                    'best_value': None,
                    'params': {},
                    'error': str(exc),
                })
        return history_records


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _print_ranked_table(ranked: list, metric_var: str):
    """Print ranked results as a plain-text table."""
    header = 'Rank  Case                           %s' % metric_var
    sep = '-' * len(header)
    print(sep)
    print(header)
    print(sep)
    for r in ranked:
        rank_str = '%4d' % r['rank'] if r['rank'] is not None else '  --'
        case_name = Path(r['case_path']).name
        val_str = '%.6g' % r['metric_value'] if r['metric_value'] is not None else 'N/A'
        print('%s  %-30s %s' % (rank_str, case_name, val_str))
    print(sep)


def _print_suggestions(suggestions: dict):
    """Print parameter refinement suggestions."""
    if not suggestions:
        print('[iteration_helper] No numeric parameters found in top cases.')
        return
    print('[iteration_helper] Suggested refined parameter ranges:')
    for key, spec in suggestions.items():
        if 'suggested_values' in spec:
            print('  %-30s  [%.6g, %.6g, %.6g]' % (
                key,
                spec['suggested_values'][0],
                spec['suggested_values'][1],
                spec['suggested_values'][2],
            ))
        else:
            print('  %-30s  values: %s' % (key, ', '.join(str(v) for v in spec['values'])))


def _print_history(history_records: list, metric_var: str):
    """Print iteration history table."""
    header = 'Iter  Best %-15s  Sweep dir' % metric_var
    sep = '-' * 65
    print(sep)
    print(header)
    print(sep)
    for rec in history_records:
        val_str = '%.6g' % rec['best_value'] if rec['best_value'] is not None else 'N/A'
        sweep_name = Path(rec['sweep_dir']).name
        print('%4d  %-20s  %s' % (rec['iteration'], val_str, sweep_name))
    print(sep)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='iteration_helper.py',
        description='Rank parametric sweep results and suggest refined parameter ranges.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python iteration_helper.py _sweep/ --metric LIQC --branch RETURN
  python iteration_helper.py _sweep/ --metric PT --branch INLET --maximize --suggest
  python iteration_helper.py _sweep/ --metric LIQC --branch RETURN --top 5 --json
  python iteration_helper.py --history _sweep1/ _sweep2/ --metric LIQC --branch RETURN
        """,
    )
    p.add_argument(
        'sweep_dir', nargs='?', default=None,
        help='Parametric sweep output directory (contains case_NNN/ subdirs)',
    )
    p.add_argument(
        '--metric', required=True, metavar='VAR',
        help='OLGA variable to rank by (e.g. LIQC, PT)',
    )
    p.add_argument(
        '--branch', default=None, metavar='BRANCH',
        help='Branch name filter (e.g. RETURN, INLET)',
    )
    p.add_argument(
        '--minimize', action='store_true', default=True,
        help='Rank by lowest metric value first (default)',
    )
    p.add_argument(
        '--maximize', action='store_true',
        help='Rank by highest metric value first',
    )
    p.add_argument(
        '--top', type=int, default=3, metavar='N',
        help='Number of top cases for refinement suggestion (default: 3)',
    )
    p.add_argument(
        '--suggest', action='store_true',
        help='Print suggested refined parameter ranges from top-N cases',
    )
    p.add_argument(
        '--json', action='store_true',
        help='Output results as JSON',
    )
    p.add_argument(
        '--history', nargs='+', metavar='DIR',
        help='Track best metric across multiple sweep directories (iterations)',
    )
    return p


def main():
    parser = _build_parser()
    args = parser.parse_args()

    minimize = not args.maximize  # --maximize overrides default --minimize

    # ------------------------------------------------------------------
    # History mode
    # ------------------------------------------------------------------
    if args.history:
        invalid = [d for d in args.history if not Path(d).is_dir()]
        if invalid:
            for d in invalid:
                print('Error: directory not found: %s' % d, file=sys.stderr)
            sys.exit(2)

        # Use any IterationHelper instance just to call history()
        try:
            helper = IterationHelper(args.history[0])
            records = helper.history(args.history, args.metric, args.branch)
        except FileNotFoundError as exc:
            print('Error: %s' % exc, file=sys.stderr)
            sys.exit(2)
        except Exception as exc:
            print('Error: %s' % exc, file=sys.stderr)
            sys.exit(1)

        if args.json:
            print(json.dumps(records, indent=2, ensure_ascii=True))
        else:
            _print_history(records, args.metric)
        sys.exit(0)

    # ------------------------------------------------------------------
    # Normal ranking mode
    # ------------------------------------------------------------------
    if not args.sweep_dir:
        parser.error('sweep_dir is required unless --history is used')

    if not Path(args.sweep_dir).is_dir():
        print('Error: directory not found: %s' % args.sweep_dir, file=sys.stderr)
        sys.exit(2)

    try:
        helper = IterationHelper(args.sweep_dir)
    except FileNotFoundError as exc:
        print('Error: %s' % exc, file=sys.stderr)
        sys.exit(2)

    try:
        ranked = helper.rank_cases(args.metric, branch=args.branch, minimize=minimize)
    except Exception as exc:
        print('Error loading results: %s' % exc, file=sys.stderr)
        sys.exit(1)

    if not ranked:
        print('Error: no case subdirectories found in %s' % args.sweep_dir, file=sys.stderr)
        sys.exit(1)

    valid_count = sum(1 for r in ranked if r['metric_value'] is not None)
    if valid_count == 0:
        print(
            'Error: metric %r not found in any .tpl file. '
            'Check --metric and --branch.' % args.metric,
            file=sys.stderr,
        )
        sys.exit(1)

    if args.json:
        output = {'ranked': ranked}
        if args.suggest:
            output['suggested_refinement'] = helper.suggest_refinement(
                args.metric, branch=args.branch, minimize=minimize, top_n=args.top
            )
        print(json.dumps(output, indent=2, ensure_ascii=True))
    else:
        _print_ranked_table(ranked, args.metric)
        if args.suggest:
            print()
            _print_suggestions(
                helper.suggest_refinement(
                    args.metric, branch=args.branch, minimize=minimize, top_n=args.top
                )
            )

    sys.exit(0)


if __name__ == '__main__':
    main()
