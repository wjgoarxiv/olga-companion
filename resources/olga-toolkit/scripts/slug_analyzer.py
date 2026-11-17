"""
slug_analyzer.py -- 3-layer slug detection for OLGA PPL spatial profile data

PROBLEM (solved here):
  OLGA PPL files contain spatial flow-regime and holdup profiles at many
  timesteps. Slug detection requires (1) reading the flow-regime ID variable,
  (2) HOL-based detection with automatic threshold selection, and (3)
  summarising slug statistics across time.

SOLUTION:
  Layer 1 - regime ID variable (REGIME_MAP lookup)
  Layer 2 - HOL bimodal threshold via Otsu's method
  Layer 3 - slug statistics and 2-D heatmap visualisation

Usage as a library:
    from slug_analyzer import SlugAnalyzer
    sa = SlugAnalyzer('results.ppl', 'PIPELINE')
    slugs = sa.detect_slugs_hol()
    stats = sa.compute_slug_stats()

Standalone usage:
    python slug_analyzer.py file.ppl --branch BR [--regime-summary]
        [--detect-slugs] [--plot regime_map.png] [--json]
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

from fast_ppl_plotter import FastPPLPlotter

# ---------------------------------------------------------------------------
# OLGA flow-regime ID lookup table
# ---------------------------------------------------------------------------
REGIME_MAP = {
    0: 'Stratified smooth',
    1: 'Stratified wavy',
    2: 'Annular',
    3: 'Slug',
    4: 'Bubble',
    5: 'Dispersed oil/water',
    6: 'Single-phase gas',
    7: 'Single-phase oil',
    8: 'Single-phase water',
}

# Canonical variable names used by OLGA PPL files
_ID_VARS = ('ID', 'REGIME', 'FLOWREGIME', 'FLOW_REGIME')
_HOL_VARS = ('HOL', 'HOLDUP', 'HL')


def _otsu_threshold(hol_array):
    """Compute Otsu's optimal threshold for bimodal HOL histogram.

    Returns a float in [0, 1].  Falls back to 0.75 if the histogram is
    unimodal (best_var == 0).
    """
    counts, edges = np.histogram(hol_array, bins=256, range=(0, 1))
    centers = (edges[:-1] + edges[1:]) / 2
    total = counts.sum()
    best_t, best_var = 0.5, 0
    w0, s0, s_total = 0, 0, np.dot(counts, centers)
    for i in range(len(counts)):
        w0 += counts[i]
        if w0 == 0:
            continue
        w1 = total - w0
        if w1 == 0:
            break
        s0 += counts[i] * centers[i]
        m0, m1 = s0 / w0, (s_total - s0) / w1
        v = w0 * w1 * (m0 - m1) ** 2
        if v > best_var:
            best_var, best_t = v, centers[i]
    return best_t if best_var > 0 else 0.75


def _find_var(plotter, branch, candidates):
    """Return the first variable name from *candidates* that exists in the PPL.

    Returns None if none found.
    """
    available = set(v.upper() for v in plotter.list_variables(branch=branch))
    for name in candidates:
        if name.upper() in available:
            return name.upper()
    return None


class SlugAnalyzer:
    """3-layer slug detector for OLGA PPL spatial profile data.

    Parameters
    ----------
    ppl_path : str
        Path to .ppl file.
    branch : str
        Branch name to analyse.
    """

    def __init__(self, ppl_path, branch):
        self.ppl_path = os.path.abspath(ppl_path)
        self.branch = branch

        self._plotter = FastPPLPlotter(self.ppl_path)
        self._timesteps = self._plotter.list_timesteps()

        # Detect ID and HOL variable names
        self._id_var = _find_var(self._plotter, branch, _ID_VARS)
        self._hol_var = _find_var(self._plotter, branch, _HOL_VARS)

        if self._id_var is None:
            warnings.warn(
                'No flow-regime ID variable found for branch %s '
                '(tried: %s). ID-based methods will return empty results.'
                % (branch, ', '.join(_ID_VARS))
            )
        if self._hol_var is None:
            warnings.warn(
                'No HOL variable found for branch %s '
                '(tried: %s). HOL-based detection unavailable.'
                % (branch, ', '.join(_HOL_VARS))
            )

    # ------------------------------------------------------------------
    # Layer 1 — flow-regime ID
    # ------------------------------------------------------------------

    def extract_flow_regimes(self, timestep=None):
        """Get flow-regime profile at one timestep.

        Parameters
        ----------
        timestep : float | None
            Seconds. None = last available timestep.

        Returns
        -------
        list of (position_m, regime_name) pairs, or [] with a warning.
        """
        if self._id_var is None:
            warnings.warn('ID variable not available; returning empty list.')
            return []

        pos, ids = self._plotter.get_profile(
            self._id_var, self.branch, timestep=timestep
        )
        if pos is None:
            warnings.warn(
                'Could not read %s for branch %s.' % (self._id_var, self.branch)
            )
            return []

        result = []
        for p, raw_id in zip(pos, ids):
            regime_name = REGIME_MAP.get(int(round(raw_id)), 'Unknown(%d)' % int(raw_id))
            result.append((float(p), regime_name))
        return result

    def regime_summary(self):
        """Compute fraction of pipe in each regime for every timestep.

        Returns
        -------
        dict : {timestep_float: {regime_name: fraction}}
            Empty dict if ID variable not available.
        """
        if self._id_var is None:
            warnings.warn('ID variable not available; returning empty dict.')
            return {}

        all_profiles = self._plotter.get_all_profiles(self._id_var, self.branch)
        summary = {}
        for ts, ids in all_profiles.items():
            n = len(ids)
            if n == 0:
                summary[ts] = {}
                continue
            counts = {}
            for raw_id in ids:
                name = REGIME_MAP.get(int(round(raw_id)), 'Unknown(%d)' % int(raw_id))
                counts[name] = counts.get(name, 0) + 1
            summary[ts] = {name: cnt / n for name, cnt in counts.items()}
        return summary

    # ------------------------------------------------------------------
    # Layer 2 — HOL-based detection
    # ------------------------------------------------------------------

    def detect_slugs_hol(self, timestep=None, threshold=None):
        """Detect slug regions using liquid holdup (HOL) profile.

        Parameters
        ----------
        timestep : float | None
            Seconds. None = last available timestep.
        threshold : float | None
            HOL threshold above which a cell is considered a slug.
            None = auto via Otsu's method (falls back to 0.75 if unimodal).

        Returns
        -------
        list of dict with keys: start_pos, end_pos, length, mean_hol.
            Empty list if HOL not available or no slugs found.
        """
        if self._hol_var is None:
            warnings.warn('HOL variable not available; returning empty list.')
            return []

        pos, hol = self._plotter.get_profile(
            self._hol_var, self.branch, timestep=timestep
        )
        if pos is None or len(hol) == 0:
            return []

        if threshold is None:
            threshold = _otsu_threshold(hol)

        in_slug = hol >= threshold
        slugs = []
        i = 0
        while i < len(in_slug):
            if in_slug[i]:
                j = i
                while j < len(in_slug) and in_slug[j]:
                    j += 1
                slug_pos = pos[i:j]
                slug_hol = hol[i:j]
                slugs.append({
                    'start_pos': float(slug_pos[0]),
                    'end_pos':   float(slug_pos[-1]),
                    'length':    float(slug_pos[-1] - slug_pos[0]),
                    'mean_hol':  float(np.mean(slug_hol)),
                })
                i = j
            else:
                i += 1
        return slugs

    # ------------------------------------------------------------------
    # Layer 3 — statistics
    # ------------------------------------------------------------------

    def compute_slug_stats(self):
        """Aggregate slug statistics across all timesteps.

        Slug count, mean/max length, and frequency estimated as number of
        slug-front crossings at the pipe outlet position over all timesteps.

        Returns
        -------
        dict with keys:
            slug_count_total, mean_length_m, max_length_m,
            outlet_crossings, timestep_count
        """
        all_hol = self._plotter.get_all_profiles(
            self._hol_var, self.branch
        ) if self._hol_var else {}

        if not all_hol:
            return {
                'slug_count_total': 0,
                'mean_length_m': 0.0,
                'max_length_m': 0.0,
                'outlet_crossings': 0,
                'timestep_count': 0,
            }

        # Compute global threshold once from all HOL values
        all_values = np.concatenate(list(all_hol.values()))
        threshold = _otsu_threshold(all_values)

        lengths = []
        # Track outlet HOL (last spatial cell) across time for frequency
        outlet_hol = []

        for ts in sorted(all_hol.keys()):
            slugs = self.detect_slugs_hol(timestep=ts, threshold=threshold)
            lengths.extend(s['length'] for s in slugs)
            hol_arr = all_hol[ts]
            if len(hol_arr) > 0:
                outlet_hol.append(float(hol_arr[-1]) >= threshold)

        # Count sign changes at outlet (low->high transitions)
        crossings = 0
        for k in range(1, len(outlet_hol)):
            if outlet_hol[k] and not outlet_hol[k - 1]:
                crossings += 1

        return {
            'slug_count_total': len(lengths),
            'mean_length_m':    float(np.mean(lengths)) if lengths else 0.0,
            'max_length_m':     float(np.max(lengths)) if lengths else 0.0,
            'outlet_crossings': crossings,
            'timestep_count':   len(all_hol),
        }

    # ------------------------------------------------------------------
    # Visualisation
    # ------------------------------------------------------------------

    def regime_map_plot(self, output=None):
        """2-D heatmap of flow regime: x=position, y=timestep, color=regime ID.

        Parameters
        ----------
        output : str | None
            Output PNG path. None = show interactively.

        Returns
        -------
        str | None : output path used, or None if ID variable unavailable.
        """
        if self._id_var is None:
            warnings.warn('ID variable not available; cannot plot regime map.')
            return None

        all_profiles = self._plotter.get_all_profiles(self._id_var, self.branch)
        if not all_profiles:
            warnings.warn('No ID profile data found for branch %s.' % self.branch)
            return None

        sorted_ts = sorted(all_profiles.keys())
        # Build 2-D array: rows = timesteps, cols = positions
        # Assume all profiles share the same position grid
        pos, _ = self._plotter.get_profile(self._id_var, self.branch)
        if pos is None:
            return None

        grid = np.zeros((len(sorted_ts), len(pos)), dtype=float)
        for i, ts in enumerate(sorted_ts):
            arr = all_profiles[ts]
            n = min(len(arr), len(pos))
            grid[i, :n] = arr[:n]

        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors

        fig, ax = plt.subplots(figsize=(12, 5))

        # Discrete colormap: one color per regime ID (0-8)
        n_regimes = 9
        cmap = plt.cm.get_cmap('tab10', n_regimes)
        bounds = np.arange(-0.5, n_regimes, 1.0)
        norm = mcolors.BoundaryNorm(bounds, cmap.N)

        ts_arr = np.array(sorted_ts, dtype=float)
        # pcolormesh needs cell edges
        pos_edges = np.concatenate([
            [pos[0] - (pos[1] - pos[0]) / 2] if len(pos) > 1 else [pos[0] - 0.5],
            (pos[:-1] + pos[1:]) / 2,
            [pos[-1] + (pos[-1] - pos[-2]) / 2] if len(pos) > 1 else [pos[-1] + 0.5],
        ])
        ts_edges = np.concatenate([
            [ts_arr[0] - (ts_arr[1] - ts_arr[0]) / 2] if len(ts_arr) > 1 else [ts_arr[0] - 0.5],
            (ts_arr[:-1] + ts_arr[1:]) / 2,
            [ts_arr[-1] + (ts_arr[-1] - ts_arr[-2]) / 2] if len(ts_arr) > 1 else [ts_arr[-1] + 0.5],
        ])

        pcm = ax.pcolormesh(pos_edges, ts_edges, grid, cmap=cmap, norm=norm)
        cbar = fig.colorbar(pcm, ax=ax, ticks=list(REGIME_MAP.keys()))
        cbar.ax.set_yticklabels(
            [REGIME_MAP[k] for k in sorted(REGIME_MAP.keys())], fontsize=7
        )
        ax.set_xlabel('Position (m)')
        ax.set_ylabel('Time (s)')
        ax.set_title('Flow Regime Map — Branch: %s' % self.branch)
        plt.tight_layout()

        if output:
            fig.savefig(output, dpi=130, bbox_inches='tight')
            plt.close(fig)
            return output
        else:
            plt.show()
            plt.close(fig)
            return None


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    ap = argparse.ArgumentParser(
        description='3-layer slug detector for OLGA PPL data'
    )
    ap.add_argument('ppl', help='Path to .ppl file')
    ap.add_argument('--branch', required=True, metavar='BR',
                    help='Branch name')
    ap.add_argument('--regime-summary', action='store_true',
                    help='Print per-timestep regime fractions')
    ap.add_argument('--detect-slugs', action='store_true',
                    help='Run HOL-based slug detection at last timestep')
    ap.add_argument('--plot', default=None, metavar='FILE',
                    help='Save 2-D regime heatmap to FILE (PNG)')
    ap.add_argument('--json', action='store_true',
                    help='Output results as JSON instead of human-readable text')
    args = ap.parse_args()

    ppl_path = os.path.abspath(args.ppl)
    if not os.path.isfile(ppl_path):
        print('ERROR: file not found: %s' % ppl_path)
        sys.exit(2)

    try:
        sa = SlugAnalyzer(ppl_path, args.branch)
    except ImportError as e:
        print('ERROR: %s' % e)
        sys.exit(2)
    except Exception as e:
        print('ERROR loading PPL: %s' % e)
        sys.exit(2)

    results = {}

    if args.regime_summary:
        summary = sa.regime_summary()
        if not summary:
            print('WARNING: no regime data available')
        results['regime_summary'] = summary

    if args.detect_slugs:
        slugs = sa.detect_slugs_hol()
        stats = sa.compute_slug_stats()
        results['slugs_last_timestep'] = slugs
        results['slug_stats'] = stats

    if args.plot:
        out = sa.regime_map_plot(output=args.plot)
        if out:
            print('Saved regime map: %s' % out)
        else:
            print('WARNING: regime map could not be generated')

    if not (args.regime_summary or args.detect_slugs or args.plot):
        # Default: print regime profile at last timestep
        regimes = sa.extract_flow_regimes()
        if not regimes:
            print('WARNING: no regime data available for branch %s' % args.branch)
            sys.exit(1)
        results['flow_regimes'] = [
            {'position_m': p, 'regime': r} for p, r in regimes
        ]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        if 'flow_regimes' in results:
            print('Flow regimes for branch %s:' % args.branch)
            print('%-14s  %s' % ('Position (m)', 'Regime'))
            for item in results['flow_regimes']:
                print('%-14.2f  %s' % (item['position_m'], item['regime']))

        if 'regime_summary' in results:
            print('Regime summary (%d timesteps):' % len(results['regime_summary']))
            for ts in sorted(results['regime_summary'].keys()):
                fracs = results['regime_summary'][ts]
                parts = ', '.join('%s: %.1f%%' % (k, v * 100)
                                  for k, v in sorted(fracs.items(),
                                                      key=lambda x: -x[1]))
                print('  t=%.1f s: %s' % (ts, parts))

        if 'slugs_last_timestep' in results:
            slugs = results['slugs_last_timestep']
            print('Slugs detected (last timestep): %d' % len(slugs))
            for i, s in enumerate(slugs):
                print('  [%d] %.1f - %.1f m (len=%.1f m, mean HOL=%.3f)' % (
                    i + 1, s['start_pos'], s['end_pos'],
                    s['length'], s['mean_hol']))

        if 'slug_stats' in results:
            st = results['slug_stats']
            print('Slug statistics across all timesteps:')
            print('  Total slugs detected : %d' % st['slug_count_total'])
            print('  Mean length          : %.2f m' % st['mean_length_m'])
            print('  Max length           : %.2f m' % st['max_length_m'])
            print('  Outlet crossings     : %d' % st['outlet_crossings'])
            print('  Timesteps analysed   : %d' % st['timestep_count'])

    sys.exit(0)


if __name__ == '__main__':
    main()
