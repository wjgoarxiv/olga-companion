"""
wax_hydrate_checker.py -- Wax/hydrate risk assessment from OLGA TPL/PPL temperature data

PROBLEM (solved here):
  OLGA results contain temperature timeseries (TPL) or spatial profiles (PPL).
  Operators need to know whether fluid temperatures drop below hydrate formation
  or wax appearance temperatures, and by how much (subcooling margin).

SOLUTION:
  1. Auto-detect TPL vs PPL from file extension.
  2. Extract TM (temperature) data via the appropriate plotter.
  3. Compute subcooling = TM - threshold_temp.
  4. Summarise risk fractions and generate margin plots.

Usage as a library:
    from wax_hydrate_checker import WaxHydrateChecker
    chk = WaxHydrateChecker('results.tpl', 'SUPPLY')
    result = chk.check_hydrate_risk(formation_temp=20.0)

Standalone usage:
    python wax_hydrate_checker.py file.tpl --branch BR --hydrate-temp 20
        [--wax-temp 35] [--plot margin.png] [--json]

Exit codes: 0=no risk, 1=risk found, 2=error.
"""

import os
import sys
import json
import argparse
import warnings
import numpy as np

# ---------------------------------------------------------------------------
# Ensure sibling modules are importable (same scripts/ directory)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# Lazy imports — resolved in __init__ based on file type
_FastTPLPlotter = None
_FastPPLPlotter = None


def _get_tpl_plotter():
    global _FastTPLPlotter
    if _FastTPLPlotter is None:
        from fast_plotter import FastTPLPlotter
        _FastTPLPlotter = FastTPLPlotter
    return _FastTPLPlotter


def _get_ppl_plotter():
    global _FastPPLPlotter
    if _FastPPLPlotter is None:
        from fast_ppl_plotter import FastPPLPlotter
        _FastPPLPlotter = FastPPLPlotter
    return _FastPPLPlotter


# Canonical OLGA temperature variable names
_TM_VARS = ('TM', 'TEMPERATURE', 'TEMP', 'TL', 'TG')


class WaxHydrateChecker:
    """Wax/hydrate risk checker from OLGA TPL or PPL temperature data.

    Parameters
    ----------
    tpl_or_ppl_path : str
        Path to .tpl or .ppl file.
    branch : str
        Branch name to analyse.
    """

    def __init__(self, tpl_or_ppl_path, branch):
        self.file_path = os.path.abspath(tpl_or_ppl_path)
        self.branch = branch

        ext = os.path.splitext(self.file_path)[1].lower()
        if ext == '.ppl':
            self._mode = 'ppl'
            cls = _get_ppl_plotter()
            self._plotter = cls(self.file_path)
            self._tm_var = self._find_var_ppl()
        else:
            # Default to TPL for .tpl and any unrecognised extension
            self._mode = 'tpl'
            cls = _get_tpl_plotter()
            self._plotter = cls(self.file_path)
            self._tm_var = self._find_var_tpl()

        if self._tm_var is None:
            warnings.warn(
                'No temperature variable found for branch %s '
                '(tried: %s).' % (branch, ', '.join(_TM_VARS))
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_var_tpl(self):
        """Find temperature variable name in TPL plotter."""
        available = set(v.upper() for v in self._plotter.available_variables(self.branch))
        for name in _TM_VARS:
            if name.upper() in available:
                return name.upper()
        return None

    def _find_var_ppl(self):
        """Find temperature variable name in PPL plotter."""
        available = set(v.upper() for v in self._plotter.list_variables(branch=self.branch))
        for name in _TM_VARS:
            if name.upper() in available:
                return name.upper()
        return None

    def _get_tm_timeseries(self):
        """Return (time_array, temp_array) from TPL or min(TM_profile) per timestep from PPL.

        Returns (None, None) if temperature not available.
        """
        if self._tm_var is None:
            return None, None

        if self._mode == 'tpl':
            t, v = self._plotter.get(self._tm_var, self.branch)
            return t, v
        else:
            # PPL: return timestep list and minimum temperature per timestep
            all_profiles = self._plotter.get_all_profiles(self._tm_var, self.branch)
            if not all_profiles:
                return None, None
            sorted_ts = sorted(all_profiles.keys())
            times = np.array(sorted_ts, dtype=float)
            temps = np.array([np.min(all_profiles[ts]) for ts in sorted_ts], dtype=float)
            return times, temps

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_hydrate_risk(self, formation_temp, subcooling_limit=0):
        """Check hydrate risk by comparing TM against hydrate formation temperature.

        Parameters
        ----------
        formation_temp : float
            Hydrate formation temperature (degrees C or K, consistent with TM units).
        subcooling_limit : float
            Minimum acceptable subcooling margin (default 0).
            Positive subcooling = safe (TM > formation_temp).

        Returns
        -------
        dict with keys:
            min_subcooling, max_subcooling, pct_at_risk, risk_times
        """
        times, temps = self._get_tm_timeseries()
        if times is None:
            return {'min_subcooling': None, 'max_subcooling': None,
                    'pct_at_risk': None, 'risk_times': []}

        subcooling = temps - formation_temp
        at_risk = subcooling < subcooling_limit
        risk_times = [float(t) for t, r in zip(times, at_risk) if r]

        return {
            'min_subcooling': float(np.min(subcooling)),
            'max_subcooling': float(np.max(subcooling)),
            'pct_at_risk':    float(np.mean(at_risk) * 100),
            'risk_times':     risk_times,
        }

    def check_wax_risk(self, wat):
        """Check wax risk by comparing TM against wax appearance temperature (WAT).

        Parameters
        ----------
        wat : float
            Wax appearance temperature (same units as TM).

        Returns
        -------
        dict with keys:
            min_subcooling, max_subcooling, pct_at_risk, risk_times
        """
        return self.check_hydrate_risk(formation_temp=wat, subcooling_limit=0)

    def compute_subcooling_timeline(self, threshold_temp):
        """Compute subcooling margin at each timestep.

        Parameters
        ----------
        threshold_temp : float
            Reference temperature (hydrate or WAT).

        Returns
        -------
        list of dict with keys:
            timestep, min_temp, subcooling, at_risk
        """
        times, temps = self._get_tm_timeseries()
        if times is None:
            return []

        result = []
        for t, temp in zip(times, temps):
            sc = float(temp) - threshold_temp
            result.append({
                'timestep':   float(t),
                'min_temp':   float(temp),
                'subcooling': sc,
                'at_risk':    sc < 0,
            })
        return result

    def margin_plot(self, thresholds, labels=None, output=None):
        """Plot TM timeseries with horizontal threshold lines and risk zones.

        Parameters
        ----------
        thresholds : list of float
            Threshold temperatures to draw as horizontal lines.
        labels : list of str | None
            Labels for each threshold. None = auto ('Threshold N').
        output : str | None
            Output PNG path. None = show interactively.

        Returns
        -------
        str | None : output path used.
        """
        times, temps = self._get_tm_timeseries()
        if times is None or temps is None:
            warnings.warn('No temperature data available for margin plot.')
            return None

        if labels is None:
            labels = ['Threshold %d' % (i + 1) for i in range(len(thresholds))]

        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(times, temps, color='steelblue', linewidth=1.4, label='Min TM (%s)' % self.branch)

        # Colour the risk zones between the lowest threshold and the curve
        if thresholds:
            lowest = min(thresholds)
            ax.fill_between(
                times, temps, lowest,
                where=(temps < lowest),
                interpolate=True,
                color='red', alpha=0.25, label='At risk'
            )
            # Yellow margin zone: within 5 degrees above threshold
            margin = 5.0
            ax.fill_between(
                times, temps, lowest,
                where=(temps >= lowest) & (temps < lowest + margin),
                interpolate=True,
                color='yellow', alpha=0.35, label='Margin (< %.0f deg above)' % margin
            )

        line_styles = ['--', '-.', ':']
        line_colors = ['red', 'orange', 'purple']
        for i, (thr, lbl) in enumerate(zip(thresholds, labels)):
            ax.axhline(
                thr,
                linestyle=line_styles[i % len(line_styles)],
                color=line_colors[i % len(line_colors)],
                linewidth=1.5,
                label='%s = %.1f' % (lbl, thr),
            )

        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Temperature')
        ax.set_title('Temperature Margin Plot — Branch: %s' % self.branch)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        if output:
            fig.savefig(output, dpi=130, bbox_inches='tight')
            plt.close(fig)
            return output
        else:
            plt.show()
            plt.close(fig)
            return None

    def risk_summary(self, hydrate_temp=None, wat=None):
        """Return human-readable risk summary text.

        Parameters
        ----------
        hydrate_temp : float | None
        wat : float | None

        Returns
        -------
        str
        """
        lines = ['Risk Summary — Branch: %s' % self.branch]

        if hydrate_temp is not None:
            r = self.check_hydrate_risk(hydrate_temp)
            if r['min_subcooling'] is None:
                lines.append('  Hydrate: no temperature data available')
            else:
                lines.append(
                    '  Hydrate (%.1f): %.1f%% of time in risk zone, '
                    'max subcooling = %.2f, min subcooling = %.2f'
                    % (hydrate_temp, r['pct_at_risk'],
                       -r['min_subcooling'] if r['min_subcooling'] < 0 else 0.0,
                       r['min_subcooling'])
                )

        if wat is not None:
            r = self.check_wax_risk(wat)
            if r['min_subcooling'] is None:
                lines.append('  Wax: no temperature data available')
            else:
                lines.append(
                    '  Wax (WAT=%.1f): %.1f%% of time in risk zone, '
                    'max subcooling = %.2f, min subcooling = %.2f'
                    % (wat, r['pct_at_risk'],
                       -r['min_subcooling'] if r['min_subcooling'] < 0 else 0.0,
                       r['min_subcooling'])
                )

        if hydrate_temp is None and wat is None:
            lines.append('  No thresholds specified.')

        return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    ap = argparse.ArgumentParser(
        description='Wax/hydrate risk checker for OLGA TPL/PPL temperature data'
    )
    ap.add_argument('file', help='Path to .tpl or .ppl file')
    ap.add_argument('--branch', required=True, metavar='BR',
                    help='Branch name')
    ap.add_argument('--hydrate-temp', type=float, default=None, metavar='TEMP',
                    help='Hydrate formation temperature')
    ap.add_argument('--wax-temp', type=float, default=None, metavar='TEMP',
                    help='Wax appearance temperature (WAT)')
    ap.add_argument('--plot', default=None, metavar='FILE',
                    help='Save temperature margin plot to FILE (PNG)')
    ap.add_argument('--json', action='store_true',
                    help='Output results as JSON')
    args = ap.parse_args()

    file_path = os.path.abspath(args.file)
    if not os.path.isfile(file_path):
        print('ERROR: file not found: %s' % file_path)
        sys.exit(2)

    if args.hydrate_temp is None and args.wax_temp is None and args.plot is None:
        print('ERROR: at least one of --hydrate-temp, --wax-temp, or --plot is required')
        ap.print_usage()
        sys.exit(2)

    try:
        chk = WaxHydrateChecker(file_path, args.branch)
    except ImportError as e:
        print('ERROR: %s' % e)
        sys.exit(2)
    except Exception as e:
        print('ERROR loading file: %s' % e)
        sys.exit(2)

    results = {}
    any_risk = False

    if args.hydrate_temp is not None:
        r = chk.check_hydrate_risk(args.hydrate_temp)
        results['hydrate_risk'] = r
        if r['pct_at_risk'] is not None and r['pct_at_risk'] > 0:
            any_risk = True

    if args.wax_temp is not None:
        r = chk.check_wax_risk(args.wax_temp)
        results['wax_risk'] = r
        if r['pct_at_risk'] is not None and r['pct_at_risk'] > 0:
            any_risk = True

    # Summary text always appended
    results['summary'] = chk.risk_summary(
        hydrate_temp=args.hydrate_temp, wat=args.wax_temp
    )

    if args.plot:
        thresholds = []
        labels = []
        if args.hydrate_temp is not None:
            thresholds.append(args.hydrate_temp)
            labels.append('Hydrate temp')
        if args.wax_temp is not None:
            thresholds.append(args.wax_temp)
            labels.append('WAT')
        out = chk.margin_plot(thresholds, labels=labels, output=args.plot)
        if out:
            print('Saved margin plot: %s' % out)
            results['plot_path'] = out
        else:
            print('WARNING: margin plot could not be generated')

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(results['summary'])

        if 'hydrate_risk' in results:
            r = results['hydrate_risk']
            if r['risk_times']:
                print('  Hydrate risk times (%d total):' % len(r['risk_times']))
                for t in r['risk_times'][:10]:
                    print('    t=%.1f s' % t)
                if len(r['risk_times']) > 10:
                    print('    ... (%d more)' % (len(r['risk_times']) - 10))

        if 'wax_risk' in results:
            r = results['wax_risk']
            if r['risk_times']:
                print('  Wax risk times (%d total):' % len(r['risk_times']))
                for t in r['risk_times'][:10]:
                    print('    t=%.1f s' % t)
                if len(r['risk_times']) > 10:
                    print('    ... (%d more)' % (len(r['risk_times']) - 10))

    sys.exit(1 if any_risk else 0)


if __name__ == '__main__':
    main()
