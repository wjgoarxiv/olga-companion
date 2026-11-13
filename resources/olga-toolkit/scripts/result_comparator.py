"""
result_comparator.py -- Multi-case result comparison for OLGA TPL/PPL files.

Overlay plots, delta analysis, summary tables across multiple simulation cases.

Usage (TPL overlay):
    python result_comparator.py case1.tpl case2.tpl --variables PT,HOL --branch BR -o _compare/

Usage (TPL delta):
    python result_comparator.py case1.tpl case2.tpl --variables PT --branch BR --delta --ref 0 -o _compare/

Usage (PPL compare):
    python result_comparator.py case1.ppl case2.ppl --variable HOL --branch BR --timestep 3600 -o _compare/

Usage (JSON summary):
    python result_comparator.py case1.tpl case2.tpl --variables PT,HOL --branch BR --json
"""

import os
import sys
import json
import argparse
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Ensure sibling modules are importable (same scripts/ directory)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from fast_plotter import FastTPLPlotter
from fast_ppl_plotter import FastPPLPlotter


# ---------------------------------------------------------------------------
# ResultComparator
# ---------------------------------------------------------------------------

class ResultComparator:
    """
    Multi-case result comparator for OLGA TPL or PPL files.

    Parameters
    ----------
    file_paths : list[str]
        List of .tpl or .ppl paths (all must be the same type).
    labels : list[str] | None
        Display names for each file. Defaults to the bare filename.
    """

    def __init__(self, file_paths, labels=None):
        if not file_paths:
            raise ValueError('file_paths must not be empty')

        exts = {os.path.splitext(p)[1].lower() for p in file_paths}
        if len(exts) > 1:
            raise ValueError('All files must be the same type (.tpl or .ppl), got: %s' % exts)

        self.file_paths = [os.path.abspath(p) for p in file_paths]
        self.file_type = list(exts)[0]  # '.tpl' or '.ppl'

        if labels is not None:
            if len(labels) != len(file_paths):
                raise ValueError('labels length must match file_paths length')
            self.labels = list(labels)
        else:
            self.labels = [os.path.basename(p) for p in self.file_paths]

        self._tpl_plotters = {}   # path -> FastTPLPlotter (loaded on demand)
        self._ppl_plotters = {}   # path -> FastPPLPlotter (loaded on demand)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_tpl(self, path, variables=None, branch=None):
        """Return (cached) FastTPLPlotter for a TPL path."""
        if path not in self._tpl_plotters:
            wanted_v = set(variables) if variables else None
            wanted_b = {branch} if branch else None
            self._tpl_plotters[path] = FastTPLPlotter(
                path,
                wanted_vars=wanted_v,
                wanted_branches=wanted_b,
            )
        return self._tpl_plotters[path]

    def _get_ppl(self, path):
        """Return (cached) FastPPLPlotter for a PPL path."""
        if path not in self._ppl_plotters:
            self._ppl_plotters[path] = FastPPLPlotter(path)
        return self._ppl_plotters[path]

    def _colors(self, n):
        """Return n distinct colors from tab10."""
        cmap = plt.cm.tab10
        return [cmap(i % 10) for i in range(n)]

    def _save_fig(self, fig, output_path):
        """Save figure and close it."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        fig.savefig(output_path, dpi=130, bbox_inches='tight')
        plt.close(fig)
        print('Saved: %s' % output_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summary_table(self, variables, branch=None):
        """
        For each file and variable compute min, max, mean, final value.

        Parameters
        ----------
        variables : list[str]
            Variable names to summarize.
        branch : str | None
            Branch name (required for TPL files).

        Returns
        -------
        list[dict]
            Each dict has keys: label, file, variable, branch, min, max, mean, final.
        """
        if self.file_type != '.tpl':
            raise NotImplementedError('summary_table is only supported for TPL files')

        rows = []
        for path, label in zip(self.file_paths, self.labels):
            plotter = self._get_tpl(path, variables=variables, branch=branch)
            for var in variables:
                t, vals = plotter.get(var, branch or '')
                if vals is None:
                    row = dict(label=label, file=os.path.basename(path),
                               variable=var, branch=branch or '',
                               min=None, max=None, mean=None, final=None)
                else:
                    row = dict(
                        label=label,
                        file=os.path.basename(path),
                        variable=var,
                        branch=branch or '',
                        min=float(np.min(vals)),
                        max=float(np.max(vals)),
                        mean=float(np.mean(vals)),
                        final=float(vals[-1]),
                    )
                rows.append(row)

        # Print formatted table
        hdr = '%-20s  %-8s  %-8s  %-12s  %-12s  %-12s  %-12s' % (
            'Label', 'Var', 'Branch', 'Min', 'Max', 'Mean', 'Final')
        sep = '-' * len(hdr)
        print(sep)
        print(hdr)
        print(sep)
        for r in rows:
            if r['min'] is None:
                print('%-20s  %-8s  %-8s  %-12s  %-12s  %-12s  %-12s' % (
                    r['label'][:20], r['variable'], r['branch'],
                    'N/A', 'N/A', 'N/A', 'N/A'))
            else:
                print('%-20s  %-8s  %-8s  %-12.4g  %-12.4g  %-12.4g  %-12.4g' % (
                    r['label'][:20], r['variable'], r['branch'],
                    r['min'], r['max'], r['mean'], r['final']))
        print(sep)

        return rows

    def overlay_plot(self, variable, branch, output=None):
        """
        Plot the same variable from each file on one axes.

        Parameters
        ----------
        variable : str
        branch : str
        output : str | None
            Full path to output PNG. If None, nothing is saved.
        """
        if self.file_type != '.tpl':
            raise NotImplementedError('overlay_plot is only supported for TPL files')

        colors = self._colors(len(self.file_paths))
        fig, ax = plt.subplots(figsize=(10, 5))

        any_plotted = False
        for (path, label, color) in zip(self.file_paths, self.labels, colors):
            plotter = self._get_tpl(path, variables=[variable], branch=branch)
            t, vals = plotter.get(variable, branch)
            if t is None or vals is None:
                print('WARNING: %s not found in %s for branch %s' % (
                    variable, os.path.basename(path), branch))
                continue
            ax.plot(t, vals, label=label, color=color, linewidth=1.4)
            any_plotted = True

        if not any_plotted:
            print('WARNING: no data to plot for %s on %s' % (variable, branch))
            plt.close(fig)
            return

        ax.set_title('Overlay: %s | Branch: %s' % (variable, branch))
        ax.set_xlabel('Time (s)')
        ax.set_ylabel(variable)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        if output:
            self._save_fig(fig, output)
        else:
            plt.close(fig)

    def delta_plot(self, variable, branch, ref=0, output=None):
        """
        Compute case[i] - case[ref] for all non-ref cases and plot delta timeseries.
        Mismatched time arrays are aligned via numpy.interp.

        Parameters
        ----------
        variable : str
        branch : str
        ref : int
            Index of the reference case in file_paths (default 0).
        output : str | None
            Full path to output PNG. If None, nothing is saved.
        """
        if self.file_type != '.tpl':
            raise NotImplementedError('delta_plot is only supported for TPL files')

        # Load reference
        ref_path = self.file_paths[ref]
        ref_plotter = self._get_tpl(ref_path, variables=[variable], branch=branch)
        t_ref, vals_ref = ref_plotter.get(variable, branch)
        if t_ref is None or vals_ref is None:
            print('ERROR: reference data not found for %s on %s in %s' % (
                variable, branch, os.path.basename(ref_path)))
            return

        colors = self._colors(len(self.file_paths))
        fig, ax = plt.subplots(figsize=(10, 5))

        any_plotted = False
        for i, (path, label, color) in enumerate(zip(
                self.file_paths, self.labels, colors)):
            if i == ref:
                continue
            plotter = self._get_tpl(path, variables=[variable], branch=branch)
            t_i, vals_i = plotter.get(variable, branch)
            if t_i is None or vals_i is None:
                print('WARNING: %s not found in %s for branch %s' % (
                    variable, os.path.basename(path), branch))
                continue

            # Align case[i] onto reference time grid via linear interpolation
            vals_i_aligned = np.interp(t_ref, t_i, vals_i)
            delta = vals_i_aligned - vals_ref

            delta_label = '%s - %s' % (label, self.labels[ref])
            ax.plot(t_ref, delta, label=delta_label, color=color, linewidth=1.4)
            any_plotted = True

        if not any_plotted:
            print('WARNING: no delta data to plot for %s on %s' % (variable, branch))
            plt.close(fig)
            return

        ax.axhline(0.0, color='black', linewidth=0.8, linestyle='--')
        ax.set_title('Delta: %s | Branch: %s | ref=%s' % (
            variable, branch, self.labels[ref]))
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Delta %s' % variable)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        if output:
            self._save_fig(fig, output)
        else:
            plt.close(fig)

    def ppl_compare(self, variable, branch, timestep, output=None):
        """
        Compare spatial profiles at a given timestep across PPL files.

        Parameters
        ----------
        variable : str
        branch : str
        timestep : float
            Target timestep in seconds (nearest match used).
        output : str | None
            Full path to output PNG. If None, nothing is saved.
        """
        if self.file_type != '.ppl':
            raise NotImplementedError('ppl_compare is only supported for PPL files')

        colors = self._colors(len(self.file_paths))
        fig, ax = plt.subplots(figsize=(10, 5))

        any_plotted = False
        for (path, label, color) in zip(self.file_paths, self.labels, colors):
            plotter = self._get_ppl(path)
            pos, vals = plotter.get_profile(variable, branch, timestep=timestep)
            if pos is None or vals is None:
                print('WARNING: %s not found in %s for branch %s' % (
                    variable, os.path.basename(path), branch))
                continue
            ax.plot(pos, vals, label=label, color=color, linewidth=1.4)
            any_plotted = True

        if not any_plotted:
            print('WARNING: no data to plot for %s on %s at t=%.1f' % (
                variable, branch, timestep))
            plt.close(fig)
            return

        ax.set_title('PPL Compare: %s | Branch: %s | t=%.1f s' % (
            variable, branch, timestep))
        ax.set_xlabel('Position (m)')
        ax.set_ylabel(variable)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        if output:
            self._save_fig(fig, output)
        else:
            plt.close(fig)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _make_out_path(out_dir, filename):
    """Build an absolute output path, creating out_dir if needed."""
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        return os.path.join(os.path.abspath(out_dir), filename)
    return None


def main():
    # Windows cp949 safety: reconfigure stdout/stderr to utf-8 with replace
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass  # Python < 3.7

    ap = argparse.ArgumentParser(
        description='Multi-case OLGA TPL/PPL result comparator')
    ap.add_argument('files', nargs='+',
                    help='Two or more .tpl or .ppl files to compare')
    ap.add_argument('--labels', default=None,
                    help='Comma-separated display labels for each file')
    ap.add_argument('--variables', '--vars', default=None,
                    help='Comma-separated variable names (TPL mode)')
    ap.add_argument('--variable', '--var', default=None,
                    help='Single variable name (PPL mode or single-var TPL mode)')
    ap.add_argument('--branch', default=None,
                    help='Branch name')
    ap.add_argument('--timestep', type=float, default=None,
                    help='Timestep in seconds for PPL comparison')
    ap.add_argument('--delta', action='store_true',
                    help='Generate delta plots (TPL only)')
    ap.add_argument('--ref', type=int, default=0,
                    help='Index of reference case for delta (default 0)')
    ap.add_argument('-o', '--output-dir', default=None,
                    help='Output directory for PNG files')
    ap.add_argument('--json', action='store_true',
                    help='Print summary table as JSON to stdout')
    args = ap.parse_args()

    # Validate inputs
    for f in args.files:
        if not os.path.isfile(f):
            print('ERROR: file not found: %s' % f)
            sys.exit(2)

    if len(args.files) < 2:
        print('ERROR: at least two files required for comparison')
        sys.exit(2)

    exts = {os.path.splitext(f)[1].lower() for f in args.files}
    if len(exts) > 1:
        print('ERROR: all files must have the same extension, got: %s' % exts)
        sys.exit(2)

    file_type = list(exts)[0]
    if file_type not in ('.tpl', '.ppl'):
        print('ERROR: unsupported file type: %s (expected .tpl or .ppl)' % file_type)
        sys.exit(2)

    labels = None
    if args.labels:
        labels = [l.strip() for l in args.labels.split(',')]
        if len(labels) != len(args.files):
            print('ERROR: --labels count (%d) must match file count (%d)' % (
                len(labels), len(args.files)))
            sys.exit(2)

    # Collect variable list
    variables = []
    if args.variables:
        variables = [v.strip() for v in args.variables.split(',')]
    if args.variable and args.variable not in variables:
        variables.append(args.variable.strip())

    if not variables and file_type == '.tpl':
        print('ERROR: --variables or --variable is required for TPL comparison')
        sys.exit(2)

    if file_type == '.ppl' and not variables:
        print('ERROR: --variable is required for PPL comparison')
        sys.exit(2)

    if file_type == '.ppl' and args.timestep is None:
        print('ERROR: --timestep is required for PPL comparison')
        sys.exit(2)

    try:
        comparator = ResultComparator(args.files, labels=labels)

        # ---- TPL mode ----
        if file_type == '.tpl':
            branch = args.branch or ''

            # Summary table (always computed)
            rows = comparator.summary_table(variables, branch=branch)

            if args.json:
                print(json.dumps(rows, indent=2))
                sys.exit(0)

            out_dir = args.output_dir

            # Overlay plots (one per variable)
            for var in variables:
                out_path = _make_out_path(out_dir, 'overlay_%s.png' % var)
                comparator.overlay_plot(var, branch, output=out_path)

            # Delta plots
            if args.delta:
                if args.ref < 0 or args.ref >= len(args.files):
                    print('ERROR: --ref index %d out of range (0-%d)' % (
                        args.ref, len(args.files) - 1))
                    sys.exit(2)
                for var in variables:
                    out_path = _make_out_path(out_dir, 'delta_%s.png' % var)
                    comparator.delta_plot(var, branch, ref=args.ref,
                                          output=out_path)

        # ---- PPL mode ----
        else:
            branch = args.branch or ''
            var = variables[0]
            out_path = _make_out_path(args.output_dir,
                                      'ppl_%s_t%.0f.png' % (var, args.timestep))
            comparator.ppl_compare(var, branch, args.timestep, output=out_path)

    except Exception as e:
        print('ERROR: %s' % e)
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
