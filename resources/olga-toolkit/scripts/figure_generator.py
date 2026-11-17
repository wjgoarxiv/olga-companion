"""
figure_generator.py -- Publication-quality visualization for OLGA simulation results.

Generates HOL profile snapshots, animations, LIQC timeseries, and rate-of-change
figures from OLGA PPL/TPL output files.

Usage as a library:
    from figure_generator import plot_hol_profile, animate_hol_profile
    fig = plot_hol_profile('results.ppl', 'BRANCH', timestep=347.0)
    animate_hol_profile('results.ppl', 'BRANCH', output='anim.gif')

Standalone usage:
    python figure_generator.py hol-profile results.ppl --branch BR --timestep 347
    python figure_generator.py animate results.ppl --branch BR -o anim.gif
    python figure_generator.py liqc-timeseries results.tpl --branch BR --criterion 1.35
    python figure_generator.py liqc-rate results.tpl --branch BR
    python figure_generator.py hol-snapshots results.ppl --branch BR --timesteps 0,100,347
"""

import os
import sys
import math
import argparse

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np

# Publication-quality style (scientific-visualization); best-effort.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from olga_plot_style import apply_style as _apply_style
    _apply_style()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Ensure sibling scripts are importable
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# ---------------------------------------------------------------------------
# Try to import publication style from scientific-visualization skill
# ---------------------------------------------------------------------------
try:
    _SCI_VIS = os.path.join(os.path.expanduser('~'), '.claude', 'skills',
                            '045_scientific-visualization', 'scripts')
    if os.path.isdir(_SCI_VIS):
        sys.path.insert(0, _SCI_VIS)
        from style_presets import rcparams
        rcparams()
except Exception:
    pass

# ---------------------------------------------------------------------------
# Default output directory
# ---------------------------------------------------------------------------
_DEFAULT_OUT_DIR = '_figures'


def _ensure_out(out_path, default_name):
    """Return resolved output path, creating directories as needed."""
    if out_path is None:
        out_path = os.path.join(_DEFAULT_OUT_DIR, default_name)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    return out_path


# ===================================================================
# 1. plot_hol_profile
# ===================================================================

def plot_hol_profile(ppl_path, branch, timestep=None, genkey_path=None,
                     flowpath=None, pipe_label=None, out_path=None):
    """Single HOL profile snapshot with optional elevation overlay.

    Parameters
    ----------
    ppl_path : str
        Path to .ppl file.
    branch : str
        Branch name.
    timestep : float or None
        Timestep in seconds. None = last available.
    genkey_path : str or None
        Path to .genkey file for elevation overlay.
    flowpath : str or None
        Flowpath label (required if genkey_path is given).
    pipe_label : str or None
        Pipe label to shade (requires genkey_path).
    out_path : str or None
        Output image path. None = _figures/plot_hol_profile.png.

    Returns
    -------
    matplotlib.figure.Figure
    """
    from fast_ppl_plotter import FastPPLPlotter

    p = FastPPLPlotter(ppl_path, wanted_branches={branch}, wanted_vars={'HOL'})
    positions, values = p.get_profile('HOL', branch, timestep=timestep)

    ts_list = p.list_timesteps()
    if timestep is not None:
        ts_arr = np.array(ts_list, dtype=float)
        actual_ts = ts_list[int(np.argmin(np.abs(ts_arr - timestep)))]
    else:
        actual_ts = ts_list[-1]

    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax1.plot(positions, values, 'b-', linewidth=1.2, label='HOL')
    ax1.set_xlabel('Position (m)')
    ax1.set_ylabel('Holdup (-)')
    ax1.set_ylim(-0.05, 1.05)
    ax1.set_title('HOL Profile  [%s]  t=%.1f s' % (branch, actual_ts))

    # Elevation overlay
    if genkey_path and flowpath:
        try:
            x_geo, y_geo = p.get_geometry(branch)
            ax2 = ax1.twinx()
            ax2.plot(x_geo, y_geo, color='gray', linewidth=0.8, alpha=0.6,
                     label='Elevation')
            ax2.set_ylabel('Elevation (m)', color='gray')
            ax2.tick_params(axis='y', labelcolor='gray')
        except Exception:
            pass

    # Pipe shading
    if pipe_label and genkey_path and flowpath:
        try:
            from pipe_mapper import PipeMapper
            pm = PipeMapper(genkey_path, flowpath)
            s, e = pm.get_section_range(pipe_label)
            if s < len(positions) and e < len(positions):
                ax1.axvspan(positions[s], positions[min(e, len(positions) - 1)],
                            alpha=0.15, color='orange',
                            label=pipe_label)
        except Exception:
            pass

    ax1.legend(loc='upper left', fontsize=8)
    fig.tight_layout()

    out_path = _ensure_out(out_path, 'plot_hol_profile.png')
    fig.savefig(out_path, dpi=600, bbox_inches='tight')
    plt.close(fig)
    return fig


# ===================================================================
# 2. animate_hol_profile
# ===================================================================

def animate_hol_profile(ppl_path, branch, genkey_path=None, flowpath=None,
                        output='animation.gif', fps=4):
    """GIF animation of HOL profile across all timesteps.

    Uses matplotlib.animation.PillowWriter (no imageio dependency).

    Parameters
    ----------
    ppl_path : str
        Path to .ppl file.
    branch : str
        Branch name.
    genkey_path : str or None
        Path to .genkey for elevation underlay.
    flowpath : str or None
        Flowpath label.
    output : str
        Output GIF path.
    fps : int
        Frames per second.
    """
    from fast_ppl_plotter import FastPPLPlotter

    p = FastPPLPlotter(ppl_path, wanted_branches={branch}, wanted_vars={'HOL'})
    all_profiles = p.get_all_profiles('HOL', branch)
    if not all_profiles:
        raise ValueError('No HOL profiles found for branch %s' % branch)

    sorted_ts = sorted(all_profiles.keys())
    positions, _ = p.get_profile('HOL', branch, timestep=sorted_ts[0])

    fig, ax = plt.subplots(figsize=(10, 4))
    line, = ax.plot([], [], 'b-', linewidth=1.2)
    ax.set_xlim(positions[0], positions[-1])
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel('Position (m)')
    ax.set_ylabel('Holdup (-)')
    title = ax.set_title('')

    # Static elevation underlay
    if genkey_path and flowpath:
        try:
            x_geo, y_geo = p.get_geometry(branch)
            ax2 = ax.twinx()
            ax2.plot(x_geo, y_geo, color='gray', linewidth=0.8, alpha=0.4)
            ax2.set_ylabel('Elevation (m)', color='gray')
            ax2.tick_params(axis='y', labelcolor='gray')
        except Exception:
            pass

    def _init():
        line.set_data([], [])
        title.set_text('')
        return line, title

    def _update(frame_idx):
        ts = sorted_ts[frame_idx]
        vals = all_profiles[ts]
        line.set_data(positions[:len(vals)], vals)
        title.set_text('HOL [%s]  t=%.1f s' % (branch, ts))
        return line, title

    anim = animation.FuncAnimation(
        fig, _update, init_func=_init,
        frames=len(sorted_ts), interval=1000 // fps, blit=True,
    )

    output = _ensure_out(output if output != 'animation.gif' else None,
                         'animate_hol_profile.gif') if output == 'animation.gif' else output
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    writer = animation.PillowWriter(fps=fps)
    anim.save(output, writer=writer)
    plt.close(fig)


# ===================================================================
# 3. plot_liqc_timeseries
# ===================================================================

def plot_liqc_timeseries(tpl_path, branch, criterion=None, out_path=None):
    """LIQC vs time from TPL data.

    Parameters
    ----------
    tpl_path : str
        Path to .tpl file.
    branch : str
        Branch name.
    criterion : float or None
        Threshold in litres. Draws red dashed line and PASS/FAIL annotation.
    out_path : str or None
        Output image path.

    Returns
    -------
    matplotlib.figure.Figure
    """
    from fast_plotter import FastTPLPlotter

    t = FastTPLPlotter(tpl_path, wanted_vars={'LIQC'}, wanted_branches={branch})
    time_arr, values = t.get('LIQC', branch)
    if time_arr is None:
        raise ValueError('LIQC data not found for branch %s' % branch)

    # Convert m3 to litres
    values_L = values * 1000.0

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(time_arr, values_L, 'b-', linewidth=1.2, label='LIQC')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Liquid Content (L)')
    ax.set_title('LIQC Timeseries  [%s]' % branch)

    if criterion is not None:
        ax.axhline(criterion, color='red', linestyle='--', linewidth=1.2,
                   label='Criterion %.2f L' % criterion)
        # Annotate PASS/FAIL at final value
        final_val = float(values_L[-1])
        status = 'PASS' if final_val <= criterion else 'FAIL'
        color = '#228833' if status == 'PASS' else '#CC3311'
        ax.text(0.98, 0.95, status, transform=ax.transAxes,
                fontsize=14, fontweight='bold', color=color,
                ha='right', va='top',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                          edgecolor=color, alpha=0.9))

    ax.legend(loc='upper left', fontsize=8)
    fig.tight_layout()

    out_path = _ensure_out(out_path, 'plot_liqc_timeseries.png')
    fig.savefig(out_path, dpi=600, bbox_inches='tight')
    plt.close(fig)
    return fig


# ===================================================================
# 4. plot_liqc_rate
# ===================================================================

def plot_liqc_rate(tpl_path, branch, out_path=None):
    """dLIQC/dt rate of change figure.

    Parameters
    ----------
    tpl_path : str
        Path to .tpl file.
    branch : str
        Branch name.
    out_path : str or None
        Output image path.

    Returns
    -------
    matplotlib.figure.Figure
    """
    from fast_plotter import FastTPLPlotter

    t = FastTPLPlotter(tpl_path, wanted_vars={'LIQC'}, wanted_branches={branch})
    time_arr, values = t.get('LIQC', branch)
    if time_arr is None:
        raise ValueError('LIQC data not found for branch %s' % branch)

    # Convert to litres then compute gradient
    values_L = values * 1000.0
    rate = np.gradient(values_L, time_arr)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(time_arr, rate, 'b-', linewidth=1.0)
    ax.axhline(0, color='gray', linewidth=0.5, linestyle='-')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('dLIQC/dt (L/s)')
    ax.set_title('LIQC Rate of Change  [%s]' % branch)
    fig.tight_layout()

    out_path = _ensure_out(out_path, 'plot_liqc_rate.png')
    fig.savefig(out_path, dpi=600, bbox_inches='tight')
    plt.close(fig)
    return fig


# ===================================================================
# 5. plot_hol_snapshots
# ===================================================================

def plot_hol_snapshots(ppl_path, branch, timesteps, genkey_path=None,
                       flowpath=None, ncols=4, out_path=None):
    """Multi-panel figure with one HOL profile panel per timestep.

    Parameters
    ----------
    ppl_path : str
        Path to .ppl file.
    branch : str
        Branch name.
    timesteps : list of float
        Timesteps to plot.
    genkey_path : str or None
        Path to .genkey for elevation underlay.
    flowpath : str or None
        Flowpath label.
    ncols : int
        Number of columns in the grid.
    out_path : str or None
        Output image path.

    Returns
    -------
    matplotlib.figure.Figure
    """
    from fast_ppl_plotter import FastPPLPlotter

    p = FastPPLPlotter(ppl_path, wanted_branches={branch}, wanted_vars={'HOL'})

    n = len(timesteps)
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows),
                             squeeze=False)

    # Pre-fetch geometry once
    geo = None
    if genkey_path and flowpath:
        try:
            geo = p.get_geometry(branch)
        except Exception:
            pass

    for i, ts in enumerate(timesteps):
        row, col = divmod(i, ncols)
        ax = axes[row][col]

        positions, values = p.get_profile('HOL', branch, timestep=ts)
        ts_list = p.list_timesteps()
        ts_arr = np.array(ts_list, dtype=float)
        actual_ts = ts_list[int(np.argmin(np.abs(ts_arr - ts)))]

        ax.plot(positions, values, 'b-', linewidth=1.0)
        ax.set_ylim(-0.05, 1.05)
        ax.set_title('t=%.1f s' % actual_ts, fontsize=9)
        ax.set_xlabel('Position (m)', fontsize=7)
        ax.set_ylabel('HOL (-)', fontsize=7)
        ax.tick_params(labelsize=6)

        if geo is not None:
            ax2 = ax.twinx()
            ax2.plot(geo[0], geo[1], color='gray', linewidth=0.5, alpha=0.4)
            ax2.tick_params(labelsize=5, labelcolor='gray')

    # Hide unused panels
    for i in range(n, nrows * ncols):
        row, col = divmod(i, ncols)
        axes[row][col].set_visible(False)

    fig.suptitle('HOL Snapshots  [%s]' % branch, fontsize=12, fontweight='bold')
    fig.tight_layout()

    out_path = _ensure_out(out_path, 'plot_hol_snapshots.png')
    fig.savefig(out_path, dpi=600, bbox_inches='tight')
    plt.close(fig)
    return fig


# ===================================================================
# CLI
# ===================================================================

def main():
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace'
        )

    ap = argparse.ArgumentParser(
        description='Publication-quality visualization for OLGA results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest='command')

    # -- hol-profile ------------------------------------------------
    sp = sub.add_parser('hol-profile', help='Single HOL profile snapshot')
    sp.add_argument('ppl', help='Path to .ppl file')
    sp.add_argument('--branch', '-b', required=True)
    sp.add_argument('--timestep', '-t', type=float, default=None)
    sp.add_argument('--genkey', '-g', default=None)
    sp.add_argument('--flowpath', default=None)
    sp.add_argument('--pipe', default=None)
    sp.add_argument('-o', '--output', default=None)

    # -- animate ----------------------------------------------------
    sp = sub.add_parser('animate', help='GIF animation of HOL profile')
    sp.add_argument('ppl', help='Path to .ppl file')
    sp.add_argument('--branch', '-b', required=True)
    sp.add_argument('--genkey', '-g', default=None)
    sp.add_argument('--flowpath', default=None)
    sp.add_argument('-o', '--output', default='animation.gif')
    sp.add_argument('--fps', type=int, default=4)

    # -- liqc-timeseries --------------------------------------------
    sp = sub.add_parser('liqc-timeseries', help='LIQC vs time')
    sp.add_argument('tpl', help='Path to .tpl file')
    sp.add_argument('--branch', '-b', required=True)
    sp.add_argument('--criterion', type=float, default=None)
    sp.add_argument('-o', '--output', default=None)

    # -- liqc-rate --------------------------------------------------
    sp = sub.add_parser('liqc-rate', help='dLIQC/dt rate of change')
    sp.add_argument('tpl', help='Path to .tpl file')
    sp.add_argument('--branch', '-b', required=True)
    sp.add_argument('-o', '--output', default=None)

    # -- hol-snapshots ----------------------------------------------
    sp = sub.add_parser('hol-snapshots', help='Multi-panel HOL snapshots')
    sp.add_argument('ppl', help='Path to .ppl file')
    sp.add_argument('--branch', '-b', required=True)
    sp.add_argument('--timesteps', required=True,
                    help='Comma-separated timesteps')
    sp.add_argument('--genkey', '-g', default=None)
    sp.add_argument('--flowpath', default=None)
    sp.add_argument('--ncols', type=int, default=4)
    sp.add_argument('-o', '--output', default=None)

    args = ap.parse_args()
    if args.command is None:
        ap.print_help()
        sys.exit(2)

    try:
        if args.command == 'hol-profile':
            fig = plot_hol_profile(
                args.ppl, args.branch, timestep=args.timestep,
                genkey_path=args.genkey, flowpath=args.flowpath,
                pipe_label=args.pipe, out_path=args.output,
            )
            print('Saved: %s' % (args.output or os.path.join(_DEFAULT_OUT_DIR, 'plot_hol_profile.png')))

        elif args.command == 'animate':
            animate_hol_profile(
                args.ppl, args.branch, genkey_path=args.genkey,
                flowpath=args.flowpath, output=args.output, fps=args.fps,
            )
            print('Saved: %s' % args.output)

        elif args.command == 'liqc-timeseries':
            fig = plot_liqc_timeseries(
                args.tpl, args.branch, criterion=args.criterion,
                out_path=args.output,
            )
            print('Saved: %s' % (args.output or os.path.join(_DEFAULT_OUT_DIR, 'plot_liqc_timeseries.png')))

        elif args.command == 'liqc-rate':
            fig = plot_liqc_rate(args.tpl, args.branch, out_path=args.output)
            print('Saved: %s' % (args.output or os.path.join(_DEFAULT_OUT_DIR, 'plot_liqc_rate.png')))

        elif args.command == 'hol-snapshots':
            ts_list = [float(x.strip()) for x in args.timesteps.split(',')]
            fig = plot_hol_snapshots(
                args.ppl, args.branch, ts_list,
                genkey_path=args.genkey, flowpath=args.flowpath,
                ncols=args.ncols, out_path=args.output,
            )
            print('Saved: %s' % (args.output or os.path.join(_DEFAULT_OUT_DIR, 'plot_hol_snapshots.png')))

    except ImportError as e:
        print('Dependency error: %s' % e, file=sys.stderr)
        sys.exit(2)
    except (ValueError, FileNotFoundError) as e:
        print('Error: %s' % e, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print('Error: %s' % e, file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
