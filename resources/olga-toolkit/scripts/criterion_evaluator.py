"""
criterion_evaluator.py -- PASS/FAIL evaluation for OLGA pipe-level liquid content.

Evaluates whether liquid content (LIQC) in a specific pipe stays within
a criterion threshold, using HOL profile data from PPL files and pipe
geometry from genkey files.

Usage as a library:
    from criterion_evaluator import CriterionEvaluator
    ev = CriterionEvaluator('results.ppl', 'model.genkey', 'FLOWPATH_1',
                            'PIPE-7', 1.35)
    result = ev.evaluate()           # single timestep (default: last)
    result = ev.evaluate(timestep=700)
    timeline = ev.evaluate_timeline()  # all timesteps

Standalone usage:
    python criterion_evaluator.py results.ppl model.genkey FLOWPATH_1 PIPE-7 1.35
    python criterion_evaluator.py results.ppl model.genkey FLOWPATH_1 PIPE-7 1.35 --timestep 700
    python criterion_evaluator.py results.ppl model.genkey FLOWPATH_1 PIPE-7 1.35 --timeline
    python criterion_evaluator.py results.ppl model.genkey FLOWPATH_1 PIPE-7 1.35 --json
"""

import os
import sys
import json
import argparse

# ---------------------------------------------------------------------------
# Ensure sibling modules are importable (same scripts/ directory)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from fast_ppl_plotter import FastPPLPlotter
from pipe_mapper import PipeMapper
from genkey_parser import GenkeyParser


class CriterionEvaluator:
    """Evaluate pipe-level liquid content against a criterion.

    Parameters
    ----------
    ppl_path : str
        Path to .ppl result file.
    genkey_path : str
        Path to .genkey input file.
    flowpath : str
        Flowpath TAG label.
    pipe_label : str
        Target pipe label within the flowpath.
    criterion_litres : float
        Maximum allowed liquid content in litres.
    branch : str or None
        PPL branch name. If None, auto-detected from genkey BRANCH LABEL.
    """

    def __init__(self, ppl_path, genkey_path, flowpath, pipe_label,
                 criterion_litres, branch=None):
        self._mapper = PipeMapper(genkey_path, flowpath)
        self._pipe_label = pipe_label
        self._criterion = float(criterion_litres)
        self._flowpath = flowpath

        # Validate pipe exists
        self._mapper.get_section_range(pipe_label)

        # Auto-detect branch from genkey if not provided
        if branch is None:
            branch = self._detect_branch(genkey_path, flowpath)

        self._branch = branch
        self._ppl = FastPPLPlotter(ppl_path, wanted_branches={branch},
                                   wanted_vars={'HOL'})

    @staticmethod
    def _detect_branch(genkey_path, flowpath_label):
        """Find BRANCH LABEL from flowpath children in genkey."""
        gk = GenkeyParser(genkey_path)
        fp = PipeMapper._find_flowpath(gk.flowpaths, flowpath_label)
        if fp is not None:
            for child in fp.get('children', []):
                if child.get('keyword') == 'BRANCH':
                    label = child['params'].get('LABEL', '')
                    if label:
                        return label
        return flowpath_label  # fallback

    def _eval_at(self, hol_array, timestep):
        """Core evaluation logic for a single HOL array."""
        liqc = self._mapper.compute_pipe_liqc(hol_array, self._pipe_label)
        verdict = 'PASS' if liqc <= self._criterion else 'FAIL'
        ratio = liqc / self._criterion if self._criterion > 0 else float('inf')
        vol_m3 = self._mapper.get_pipe_volume(self._pipe_label)
        vol_litres = vol_m3 * 1000.0
        fill = liqc / vol_litres if vol_litres > 0 else 0.0
        return {
            'verdict': verdict,
            'liqc_litres': liqc,
            'criterion_litres': self._criterion,
            'ratio': ratio,
            'timestep': timestep,
            'pipe_label': self._pipe_label,
            'pipe_volume_litres': vol_litres,
            'fill_fraction': fill,
        }

    def evaluate(self, timestep=None):
        """Evaluate at a single timestep (default: last).

        Returns
        -------
        dict with keys: verdict, liqc_litres, criterion_litres, ratio,
            timestep, pipe_label, pipe_volume_litres, fill_fraction.
        """
        _, hol = self._ppl.get_profile('HOL', self._branch, timestep=timestep)
        if timestep is None:
            ts = self._ppl.list_timesteps()[-1]
        else:
            # Resolve to nearest actual timestep
            import numpy as np
            ts_arr = np.array(self._ppl.list_timesteps(), dtype=float)
            ts = float(ts_arr[int(np.argmin(np.abs(ts_arr - timestep)))])
        return self._eval_at(hol, ts)

    def evaluate_timeline(self):
        """Evaluate across all timesteps.

        Returns
        -------
        dict with keys: timeline, first_pass_time, final_verdict,
            min_liqc, max_liqc, transitions.
        """
        all_profiles = self._ppl.get_all_profiles('HOL', self._branch)
        timeline = []
        min_liqc = float('inf')
        max_liqc = float('-inf')
        first_pass = None
        prev_verdict = None
        transitions = []

        for ts in sorted(all_profiles.keys()):
            hol = all_profiles[ts]
            result = self._eval_at(hol, ts)
            entry = {
                'timestep': ts,
                'verdict': result['verdict'],
                'liqc_litres': result['liqc_litres'],
                'ratio': result['ratio'],
            }
            timeline.append(entry)

            if result['liqc_litres'] < min_liqc:
                min_liqc = result['liqc_litres']
            if result['liqc_litres'] > max_liqc:
                max_liqc = result['liqc_litres']

            if result['verdict'] == 'PASS' and first_pass is None:
                first_pass = ts

            if prev_verdict is not None and result['verdict'] != prev_verdict:
                transitions.append({
                    'timestep': ts,
                    'from': prev_verdict,
                    'to': result['verdict'],
                })
            prev_verdict = result['verdict']

        final_verdict = timeline[-1]['verdict'] if timeline else 'FAIL'

        return {
            'timeline': timeline,
            'first_pass_time': first_pass,
            'final_verdict': final_verdict,
            'min_liqc': min_liqc if min_liqc != float('inf') else 0.0,
            'max_liqc': max_liqc if max_liqc != float('-inf') else 0.0,
            'transitions': transitions,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_single(result):
    """Print single evaluation result."""
    print('Criterion Evaluation: %s in %s' % (
        result['pipe_label'], result.get('_flowpath', '')))
    print('  Timestep:    %.1f s' % result['timestep'])
    print('  LIQC:        %.3f L' % result['liqc_litres'])
    print('  Criterion:   %.3f L' % result['criterion_litres'])
    print('  Ratio:       %.2fx' % result['ratio'])
    print('  Verdict:     %s' % result['verdict'])
    print('')
    print('  Pipe Volume: %.3f L' % result['pipe_volume_litres'])
    print('  Fill:        %.1f%%' % (result['fill_fraction'] * 100.0))


def _print_timeline(tl_result, criterion, pipe_label):
    """Print timeline evaluation result."""
    print('Criterion Timeline: %s (criterion: %.2f L)' % (
        pipe_label, criterion))

    for entry in tl_result['timeline']:
        print('  t=%.1f s     %-4s  %.3f L (%.2fx)' % (
            entry['timestep'], entry['verdict'],
            entry['liqc_litres'], entry['ratio']))

    print('')
    if tl_result['first_pass_time'] is not None:
        print('  First PASS: %.1f s' % tl_result['first_pass_time'])
    else:
        print('  First PASS: never')

    final_liqc = tl_result['timeline'][-1]['liqc_litres'] if tl_result['timeline'] else 0.0
    print('  Final:      %s (%.3f L)' % (tl_result['final_verdict'], final_liqc))

    if tl_result['transitions']:
        parts = ['%s->%s at t=%.1f' % (t['from'], t['to'], t['timestep'])
                 for t in tl_result['transitions']]
        print('  Transitions: %s' % ', '.join(parts))
    else:
        print('  Transitions: none')


def main():
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace'
        )

    ap = argparse.ArgumentParser(
        description='PASS/FAIL evaluation for OLGA pipe-level liquid content',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('ppl', help='Path to .ppl result file')
    ap.add_argument('genkey', help='Path to .genkey input file')
    ap.add_argument('flowpath', help='Flowpath TAG label')
    ap.add_argument('pipe', help='Target pipe label')
    ap.add_argument('criterion', type=float,
                    help='Maximum allowed liquid content (litres)')
    ap.add_argument('--timestep', '-t', type=float,
                    help='Evaluate at specific timestep (default: last)')
    ap.add_argument('--timeline', action='store_true',
                    help='Evaluate across all timesteps')
    ap.add_argument('--branch', '-b',
                    help='PPL branch name (default: auto-detect from genkey)')
    ap.add_argument('--json', '-j', action='store_true',
                    help='Output as JSON')
    args = ap.parse_args()

    try:
        ev = CriterionEvaluator(
            args.ppl, args.genkey, args.flowpath, args.pipe,
            args.criterion, branch=args.branch,
        )
    except Exception as e:
        print('Error: %s' % e, file=sys.stderr)
        sys.exit(2)

    try:
        if args.timeline:
            tl = ev.evaluate_timeline()
            if args.json:
                print(json.dumps(tl, indent=2))
            else:
                _print_timeline(tl, args.criterion, args.pipe)
            # Exit code based on final verdict
            sys.exit(0 if tl['final_verdict'] == 'PASS' else 1)
        else:
            result = ev.evaluate(timestep=args.timestep)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                result['_flowpath'] = args.flowpath
                _print_single(result)
            sys.exit(0 if result['verdict'] == 'PASS' else 1)
    except Exception as e:
        print('Error: %s' % e, file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
