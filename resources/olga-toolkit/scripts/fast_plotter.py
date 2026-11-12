"""
fast_plotter.py — Optimized TPL result plotter for OLGA

PROBLEM (solved here):
  The naive approach calls `reader.extract(*all_indices)` with every variable in the
  catalog (often 2000-3000 entries). On 40-60 MB TPL files this is slow and
  produces plots with too many points to be useful.

SOLUTION:
  1. Extract ONLY the (variable, branch) pairs you actually need — not the full catalog.
  2. Downsample time series to MAX_PTS before handing to matplotlib.
  3. Avoid Unicode characters in print() output on Windows (cp949 codec issue).

Usage as a library:
    from fast_plotter import FastTPLPlotter
    p = FastTPLPlotter('results.tpl', max_pts=500)
    t, v = p.get('PT', 'SUPPLY')   # returns (time_array, value_array) downsampled

Standalone usage:
    python fast_plotter.py results.tpl --out-dir _plots/ --branches SUPPLY,RETURN --vars PT,HOL,GT
"""

import os
import re
import sys
import argparse
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Ensure result_parser is importable (same scripts/ directory)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from result_parser import ResultParser

try:
    from olga_plot_style import apply_style, save_figure, PALETTE
except ImportError:  # pragma: no cover - style is best-effort
    def apply_style():
        pass

    def save_figure(fig, path, dpi=600, transparent=True):
        fig.savefig(path, dpi=dpi, bbox_inches='tight')
        return str(path)

    PALETTE = None


class FastTPLPlotter:
    """
    Efficient TPL plotter that extracts only requested series and downsamples.

    Parameters
    ----------
    tpl_path : str
        Absolute path to the OLGA .tpl file.
    max_pts : int
        Maximum number of time points per series (default 500).
        Series with more points are strided down uniformly.
    wanted_branches : set[str] | None
        Branch names to pre-filter. None = accept all.
    wanted_vars : set[str] | None
        Variable names to pre-filter. None = accept all.
    """

    # Regex to extract branch name from OLGA position string
    # e.g. "SECTION - Br - SUPPLY - PIPE - PIPE-1 - NR - 1"
    _BR_RE = re.compile(r'Br - ([A-Z0-9_\-]+)')

    def __init__(self, tpl_path: str, max_pts: int = 500,
                 wanted_branches=None, wanted_vars=None):
        self.tpl_path = tpl_path
        self.max_pts = max_pts

        print('Loading TPL: %s' % os.path.basename(tpl_path))
        self._parser = ResultParser(tpl_path)
        catalog = self._parser.list_variables()
        print('  %d variables in catalog' % len(catalog))

        # Build targeted index map
        self._index_map = {}  # (var, branch) -> reader index
        needed = set()

        for v in catalog:
            var = v['variable']
            m = self._BR_RE.search(v['position'])
            br = m.group(1) if m else ''

            if wanted_vars and var not in wanted_vars:
                continue
            # Only branch-scoped trends (position contains "Br - <name>") are
            # filtered by branch. POSITION-based trends (br == '') are not tied
            # to a branch and always pass.
            if wanted_branches and br and br not in wanted_branches:
                continue

            key = (var, br)
            if key not in self._index_map:
                self._index_map[key] = v['index']
                needed.add(v['index'])

        print('  Extracting %d targeted series (skipped %d)' % (
            len(needed), len(catalog) - len(needed)))

        if needed:
            self._parser._reader.extract(*needed)
        else:
            print('  WARNING: no series matched the requested branches/vars; '
                  'nothing to plot')

        # Compute stride (guard against an empty / 0-d time vector)
        time_raw = np.atleast_1d(np.asarray(self._parser._reader.time, dtype=float))
        n = int(time_raw.size)
        self._stride = max(1, n // self.max_pts)
        self._time = time_raw[::self._stride]

        print('  Time: %.1f-%.1fs | %d pts (stride=%d)' % (
            float(self._time[0]) if len(self._time) else 0,
            float(self._time[-1]) if len(self._time) else 0,
            len(self._time),
            self._stride,
        ))

    @property
    def time(self) -> np.ndarray:
        """Downsampled time array (seconds)."""
        return self._time

    def get(self, variable: str, branch: str):
        """
        Return (time, values) for the given (variable, branch) pair.
        Both arrays are downsampled to max_pts.
        Returns (None, None) if not found.
        """
        idx = self._index_map.get((variable, branch))
        if idx is None:
            return None, None
        raw = self._parser._reader.data.get(idx)
        if raw is None:
            return None, None
        return self._time, np.array(raw)[::self._stride]

    def available_branches(self, variable: str = None):
        """List branches that have data for the given variable (or all)."""
        if variable:
            return [br for (var, br) in self._index_map if var == variable]
        return list({br for (_, br) in self._index_map})

    def available_variables(self, branch: str = None):
        """List variables that have data for the given branch (or all)."""
        if branch:
            return [var for (var, br) in self._index_map if br == branch]
        return list({var for (var, _) in self._index_map})


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------
_DEFAULT_VARS    = ['PT', 'HOL', 'TM', 'ACCLIQ', 'GT', 'QG']
_UNIT_SCALE      = {'PT': (1e-3, 'kPa'), 'ACCLIQ': (1e3, 'L')}
_ACCLIQ_TARGET_L = None    # set via --criterion; no line drawn by default


def _make_plots(tpl_path: str, out_dir: str, branches: list,
                variables: list, max_pts: int, title_prefix: str):
    """Generate a 6-panel overview PNG and a return-line detail PNG."""
    os.makedirs(out_dir, exist_ok=True)
    apply_style()  # publication-quality rcParams (scientific-visualization)

    wanted_b = set(branches)
    wanted_v = set(variables)
    plotter = FastTPLPlotter(tpl_path, max_pts=max_pts,
                             wanted_branches=wanted_b, wanted_vars=wanted_v)
    t_max = float(plotter.time[-1]) if len(plotter.time) else 0

    colors = PALETTE if PALETTE else list(plt.cm.tab10.colors)

    # Overview: one panel per variable, all branches overlaid
    ncols = 3
    nrows = -(-len(variables) // ncols)  # ceiling division
    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 4 * nrows))
    fig.suptitle('%s  t=0-%.0fs' % (title_prefix, t_max),
                 fontsize=13, fontweight='bold')
    ax_flat = np.array(axes).flatten()

    for i, var in enumerate(variables):
        ax = ax_flat[i]
        sc, unit = _UNIT_SCALE.get(var, (1.0, var))
        # Plot every branch that actually has data for this variable (includes
        # POSITION-based trends, whose branch key is '').
        plot_branches = plotter.available_branches(var) or list(branches)
        for j, br in enumerate(plot_branches):
            t, v = plotter.get(var, br)
            if t is not None:
                ax.plot(t, v * sc, color=colors[j % len(colors)],
                        label=(br or 'trend'), linewidth=1.6)
        if var == 'ACCLIQ' and _ACCLIQ_TARGET_L is not None:
            ax.axhline(_ACCLIQ_TARGET_L, color='red', ls='--', lw=1.5,
                       label='%.2f L target' % _ACCLIQ_TARGET_L)
        ax.set_title('%s (%s)' % (var, unit))
        ax.set_xlabel('Time (s)')
        ax.grid(False)
        ax.legend(fontsize=6)

    # Hide unused axes
    for ax in ax_flat[len(variables):]:
        ax.set_visible(False)

    fig.tight_layout()
    out = os.path.join(out_dir, 'overview.png')
    save_figure(fig, out, dpi=600, transparent=False)
    plt.close(fig)
    print('Saved: %s' % out)
    return out


def main():
    ap = argparse.ArgumentParser(description='Fast OLGA TPL plotter')
    ap.add_argument('tpl', help='Path to .tpl file')
    ap.add_argument('--out-dir', default='_plots', help='Output directory')
    ap.add_argument('--branches', default=None,
                    help='Comma-separated branch names (default: auto-detect up to 5)')
    ap.add_argument('--vars', default=','.join(_DEFAULT_VARS),
                    help='Comma-separated variable names')
    ap.add_argument('--max-pts', type=int, default=500,
                    help='Max time points per series (default 500)')
    ap.add_argument('--title', default='OLGA TPL',
                    help='Plot title prefix')
    ap.add_argument('--criterion', type=float, default=None,
                    help='ACCLIQ criterion in litres (draws red dashed line)')
    args = ap.parse_args()

    global _ACCLIQ_TARGET_L
    if args.criterion is not None:
        _ACCLIQ_TARGET_L = args.criterion

    if args.branches:
        branches = [b.strip() for b in args.branches.split(',')]
    else:
        # Auto-detect branches from TPL catalog (up to 5)
        _tmp = ResultParser(args.tpl)
        catalog = _tmp.list_variables()
        import re as _re
        _br_re = _re.compile(r'Br - ([A-Z0-9_\-]+)')
        seen = []
        for v in catalog:
            m = _br_re.search(v.get('position', ''))
            if m:
                br = m.group(1)
                if br not in seen:
                    seen.append(br)
                    if len(seen) >= 5:
                        break
        branches = seen if seen else ['PIPELINE']
        print('Auto-detected branches: %s' % ', '.join(branches))

    variables = [v.strip() for v in args.vars.split(',')]

    _make_plots(
        tpl_path=args.tpl,
        out_dir=args.out_dir,
        branches=branches,
        variables=variables,
        max_pts=args.max_pts,
        title_prefix=args.title,
    )


if __name__ == '__main__':
    main()
