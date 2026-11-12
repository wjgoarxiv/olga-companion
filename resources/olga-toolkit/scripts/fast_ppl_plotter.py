"""
fast_ppl_plotter.py -- PPL (Profile Plot) spatial profile extractor for OLGA

PROBLEM (solved here):
  OLGA PPL files contain spatial profiles (e.g. pressure, holdup, temperature
  along a pipeline) at many timesteps.  The pyfas.Ppl reader auto-loads all
  data on init, so the bottleneck is not I/O but navigating the nested dict
  structure and finding the right (branch, variable, timestep) combination.

SOLUTION:
  1. Wrap pyfas.Ppl with a filtered, numpy-friendly API.
  2. Provide nearest-timestep matching so callers don't need exact floats.
  3. Batch-export PNG profiles via matplotlib Agg backend.
  4. Avoid Unicode characters in print() output on Windows (cp949 codec issue).

Usage as a library:
    from fast_ppl_plotter import FastPPLPlotter
    p = FastPPLPlotter('results.ppl')
    pos, vals = p.get_profile('HOL', 'RETURN')
    x, y = p.get_geometry('RETURN')

Standalone usage:
    python fast_ppl_plotter.py results.ppl --list-branches
    python fast_ppl_plotter.py results.ppl --list-vars --branch RETURN
    python fast_ppl_plotter.py results.ppl --list-timesteps
    python fast_ppl_plotter.py results.ppl --branch RETURN --var HOL --timestep 3600
    python fast_ppl_plotter.py results.ppl --branch RETURN --var HOL --all-timesteps --out-dir _ppl/
    python fast_ppl_plotter.py results.ppl --geometry RETURN
"""

import os
import sys
import argparse
import numpy as np

# ---------------------------------------------------------------------------
# Ensure sibling modules are importable (same scripts/ directory)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from pyfas import Ppl
    PYFAS_AVAILABLE = True
except ImportError:
    PYFAS_AVAILABLE = False


class FastPPLPlotter:
    """Efficient PPL profile extractor for OLGA spatial data.

    Parameters
    ----------
    ppl_path : str
        Path to .ppl file.
    wanted_branches : set[str] | None
        Branch names to filter. None = accept all.
    wanted_vars : set[str] | None
        Variable names to filter. None = accept all.
    """

    def __init__(self, ppl_path, wanted_branches=None, wanted_vars=None):
        if not PYFAS_AVAILABLE:
            raise ImportError('pyfas is required but not installed')

        self.ppl_path = ppl_path
        self._wanted_branches = set(wanted_branches) if wanted_branches else None
        self._wanted_vars = set(wanted_vars) if wanted_vars else None

        print('Loading PPL: %s' % os.path.basename(ppl_path))
        self._ppl = Ppl(ppl_path)

        # Cache branch list and timesteps (actual pyfas API)
        self._all_branches = sorted(self._ppl.geometries.keys())
        self._all_timesteps = list(self._ppl.time)

        # Discover available variables per branch via filter_data catalog
        import re as _re
        _br_re = _re.compile(r"'BRANCH:'\s+'([^']+)'")
        self._vars_by_branch = {}
        self._catalog_index = {}  # (var_upper, branch) -> idx
        all_catalog = self._ppl.filter_data('')
        for idx, raw_line in all_catalog.items():
            parts = raw_line.split()
            var_name = parts[0] if parts else ''
            br_match = _br_re.search(raw_line)
            branch = br_match.group(1) if br_match else ''
            if branch not in self._vars_by_branch:
                self._vars_by_branch[branch] = []
            if var_name not in self._vars_by_branch[branch]:
                self._vars_by_branch[branch].append(var_name)
            key = (var_name.upper(), branch)
            if key not in self._catalog_index:
                self._catalog_index[key] = idx

        # Pre-extract all needed indices
        needed = set()
        for (var_u, br), idx in self._catalog_index.items():
            if self._branch_ok(br) and self._var_ok(var_u):
                needed.add(idx)
        for idx in needed:
            self._ppl.extract(idx)

        # Count how many (branch, var) pairs pass filter
        total = sum(len(v) for v in self._vars_by_branch.values())
        filtered = 0
        for br in self._all_branches:
            for var in self._vars_by_branch.get(br, []):
                if self._branch_ok(br) and self._var_ok(var):
                    filtered += 1

        print('  %d branches, %d timesteps' % (
            len(self._all_branches), len(self._all_timesteps)))
        print('  %d total (branch, var) pairs, %d after filter' % (
            total, filtered))

        if self._all_timesteps:
            print('  Time range: %.1f - %.1f s' % (
                float(self._all_timesteps[0]),
                float(self._all_timesteps[-1])))

    def _branch_ok(self, branch):
        """Check if branch passes the wanted filter."""
        if self._wanted_branches is None:
            return True
        return branch in self._wanted_branches

    def _var_ok(self, variable):
        """Check if variable passes the wanted filter."""
        if self._wanted_vars is None:
            return True
        return variable in self._wanted_vars

    def _resolve_timestep(self, timestep):
        """Find the nearest available timestep to the requested value."""
        ts_arr = np.array(self._all_timesteps, dtype=float)
        idx = int(np.argmin(np.abs(ts_arr - timestep)))
        return self._all_timesteps[idx]

    def get_profile(self, variable, branch, timestep=None):
        """Get spatial profile at one timestep.

        Parameters
        ----------
        variable : str
            Variable name (e.g. 'HOL', 'PT', 'TM').
        branch : str
            Branch name.
        timestep : float | None
            Timestep in seconds. None = last available.

        Returns
        -------
        (positions, values) : tuple of numpy arrays
            positions = pipeline position in metres, values = variable values.
            Returns (None, None) if not found.
        """
        if not self._branch_ok(branch) or not self._var_ok(variable):
            return None, None

        key = (variable.upper(), branch)
        idx = self._catalog_index.get(key)
        if idx is None:
            # Case-insensitive branch fallback
            for (v, b), i in self._catalog_index.items():
                if v == variable.upper() and b.upper() == branch.upper():
                    idx = i
                    break
        if idx is None:
            return None, None

        raw = self._ppl.data[idx]
        positions = np.array(raw[0], dtype=float)
        values_per_ts = raw[1]

        # Resolve timestep index
        ts_idx = -1  # default: last
        if timestep is not None:
            ts_idx = int(np.argmin(np.abs(
                np.array(self._all_timesteps, dtype=float) - timestep)))

        values = np.array(values_per_ts[ts_idx], dtype=float)
        return positions, values

    def get_all_profiles(self, variable, branch):
        """Get all timestep profiles for a variable on a branch.

        Returns
        -------
        dict : {timestep_float: values_ndarray}
            Empty dict if not found or filtered out.
        """
        if not self._branch_ok(branch) or not self._var_ok(variable):
            return {}

        key = (variable.upper(), branch)
        idx = self._catalog_index.get(key)
        if idx is None:
            for (v, b), i in self._catalog_index.items():
                if v == variable.upper() and b.upper() == branch.upper():
                    idx = i
                    break
        if idx is None:
            return {}

        raw = self._ppl.data[idx]
        values_per_ts = raw[1]
        result = {}
        for i, ts in enumerate(self._all_timesteps):
            if i < len(values_per_ts):
                result[float(ts)] = np.array(values_per_ts[i], dtype=float)
        return result

    def get_geometry(self, branch):
        """Get branch geometry (x-position, y-elevation).

        Returns
        -------
        (x, y) : tuple of numpy arrays
            Returns (None, None) if not found.
        """
        if not self._branch_ok(branch):
            return None, None

        try:
            x, y = self._ppl.geometries[branch]
            return np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        except KeyError:
            return None, None

    def list_timesteps(self):
        """Return list of available timesteps (seconds)."""
        return list(self._all_timesteps)

    def list_branches(self):
        """Return list of branch names (filtered if wanted_branches set)."""
        if self._wanted_branches is None:
            return list(self._all_branches)
        return [b for b in self._all_branches if b in self._wanted_branches]

    def list_variables(self, branch=None):
        """Return list of variable names.

        Parameters
        ----------
        branch : str | None
            If given, only variables for that branch. Otherwise union of all.
        """
        if branch is not None:
            if not self._branch_ok(branch):
                return []
            raw = self._vars_by_branch.get(branch, [])
            if self._wanted_vars is None:
                return list(raw)
            return [v for v in raw if v in self._wanted_vars]

        seen = set()
        result = []
        for br in self._all_branches:
            if not self._branch_ok(br):
                continue
            for v in self._vars_by_branch.get(br, []):
                if self._var_ok(v) and v not in seen:
                    seen.add(v)
                    result.append(v)
        return result


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

def _plot_profile(positions, values, variable, branch, timestep,
                  out_path):
    """Save a single profile plot as PNG."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    try:
        import os as _os
        import sys as _sys
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        from olga_plot_style import apply_style, save_figure, PALETTE
        apply_style()
        _color = PALETTE[0] if PALETTE else None
    except ImportError:
        def save_figure(fig, path, dpi=600, transparent=False):
            fig.savefig(path, dpi=dpi, bbox_inches='tight')
        _color = None

    fig, ax = plt.subplots(figsize=(7.5, 3.2), layout='constrained')
    ax.plot(positions, values, linewidth=1.6, color=_color)
    ax.set_title('%s on %s at t=%.1f s' % (variable, branch, timestep))
    ax.set_xlabel('Position (m)')
    ax.set_ylabel(variable)
    save_figure(fig, out_path, dpi=600, transparent=False)
    plt.close(fig)


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    ap = argparse.ArgumentParser(
        description='Fast OLGA PPL profile extractor and plotter')
    ap.add_argument('ppl', help='Path to .ppl file')
    ap.add_argument('--branch', default=None,
                    help='Branch name')
    ap.add_argument('--var', default=None,
                    help='Variable name (e.g. HOL, PT, TM)')
    ap.add_argument('--timestep', type=float, default=None,
                    help='Timestep in seconds (nearest match)')
    ap.add_argument('--all-timesteps', action='store_true',
                    help='Export profiles for all timesteps')
    ap.add_argument('--out-dir', default='_ppl',
                    help='Output directory for PNG plots')
    ap.add_argument('--list-branches', action='store_true',
                    help='List available branches and exit')
    ap.add_argument('--list-vars', action='store_true',
                    help='List available variables and exit')
    ap.add_argument('--list-timesteps', action='store_true',
                    help='List available timesteps and exit')
    ap.add_argument('--geometry', default=None, metavar='BRANCH',
                    help='Print geometry (x, y) for a branch and exit')
    args = ap.parse_args()

    ppl_path = os.path.abspath(args.ppl)
    if not os.path.isfile(ppl_path):
        print('ERROR: file not found: %s' % ppl_path)
        sys.exit(2)

    try:
        plotter = FastPPLPlotter(ppl_path)
    except ImportError as e:
        print('ERROR: %s' % e)
        sys.exit(2)
    except Exception as e:
        print('ERROR loading PPL: %s' % e)
        sys.exit(2)

    # --list-branches
    if args.list_branches:
        branches = plotter.list_branches()
        print('Branches (%d):' % len(branches))
        for b in branches:
            print('  %s' % b)
        sys.exit(0)

    # --list-vars
    if args.list_vars:
        variables = plotter.list_variables(branch=args.branch)
        label = 'Variables'
        if args.branch:
            label = 'Variables for %s' % args.branch
        print('%s (%d):' % (label, len(variables)))
        for v in variables:
            print('  %s' % v)
        sys.exit(0)

    # --list-timesteps
    if args.list_timesteps:
        ts = plotter.list_timesteps()
        print('Timesteps (%d):' % len(ts))
        for t in ts:
            print('  %.2f' % float(t))
        sys.exit(0)

    # --geometry BRANCH
    if args.geometry:
        x, y = plotter.get_geometry(args.geometry)
        if x is None:
            print('ERROR: geometry not found for branch: %s' % args.geometry)
            sys.exit(1)
        print('Geometry for %s (%d points):' % (args.geometry, len(x)))
        print('%-14s  %s' % ('X (m)', 'Y (m)'))
        for xi, yi in zip(x, y):
            print('%-14.4f  %.4f' % (xi, yi))
        sys.exit(0)

    # Profile extraction requires --branch and --var
    if not args.branch or not args.var:
        print('ERROR: --branch and --var are required for profile extraction')
        ap.print_usage()
        sys.exit(1)

    # --all-timesteps mode: generate PNG per timestep
    if args.all_timesteps:
        out_dir = os.path.abspath(args.out_dir)
        os.makedirs(out_dir, exist_ok=True)

        profiles = plotter.get_all_profiles(args.var, args.branch)
        if not profiles:
            print('ERROR: no data for %s on %s' % (args.var, args.branch))
            sys.exit(1)

        # Need positions array from one profile call
        pos, _ = plotter.get_profile(args.var, args.branch)
        if pos is None:
            print('ERROR: could not get positions for %s on %s' % (
                args.var, args.branch))
            sys.exit(1)

        sorted_ts = sorted(profiles.keys())
        print('Plotting %d profiles to %s ...' % (len(sorted_ts), out_dir))

        for i, ts in enumerate(sorted_ts):
            vals = profiles[ts]
            fname = '%s_%s_t%08.1f.png' % (args.branch, args.var, ts)
            out_path = os.path.join(out_dir, fname)
            _plot_profile(pos, vals, args.var, args.branch, ts, out_path)
            if (i + 1) % 50 == 0 or (i + 1) == len(sorted_ts):
                print('  %d / %d done' % (i + 1, len(sorted_ts)))

        print('Saved %d PNGs to %s' % (len(sorted_ts), out_dir))
        sys.exit(0)

    # Single timestep: print to stdout
    pos, vals = plotter.get_profile(args.var, args.branch,
                                    timestep=args.timestep)
    if pos is None:
        print('ERROR: no data for %s on %s' % (args.var, args.branch))
        sys.exit(1)

    # Report which timestep was actually used
    if args.timestep is not None:
        actual_t = plotter._resolve_timestep(args.timestep)
        print('# %s on %s at t=%.2f s (requested %.2f s)' % (
            args.var, args.branch, float(actual_t), args.timestep))
    else:
        ts = plotter.list_timesteps()
        last_t = float(ts[-1]) if ts else 0
        print('# %s on %s at t=%.2f s (last timestep)' % (
            args.var, args.branch, last_t))

    print('%-14s  %s' % ('Position(m)', args.var))
    for p, v in zip(pos, vals):
        print('%-14.6f  %.6f' % (p, v))

    sys.exit(0)


if __name__ == '__main__':
    main()
