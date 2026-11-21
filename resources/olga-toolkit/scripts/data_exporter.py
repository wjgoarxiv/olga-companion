"""
data_exporter.py -- Export OLGA results (.tpl/.ppl) to CSV, Excel, or pandas DataFrame.

Usage as a library:
    from data_exporter import DataExporter

    # TPL (time series)
    exp = DataExporter('results.tpl')
    df  = exp.to_dataframe(['PT', 'HOL'], branch='RETURN')
    exp.to_csv(['PT', 'HOL'], branch='RETURN', output='results.csv')
    exp.to_excel(['PT', 'HOL'], branch='RETURN', output='results.xlsx')

    # PPL (spatial profile)
    exp = DataExporter('results.ppl')
    df  = exp.to_dataframe(['HOL'], branch='PIPELINE', timestep=3600)
    exp.to_csv(['HOL'], branch='PIPELINE', timestep=3600, output='profile.csv')

CLI:
    python data_exporter.py results.tpl --variables PT,HOL --branch RETURN -o results.csv
    python data_exporter.py results.tpl --variables PT,HOL --branch RETURN --excel -o results.xlsx
    python data_exporter.py results.ppl --variables HOL --branch PIPELINE --timestep 3600 -o profile.csv
    python data_exporter.py results.tpl --variables PT --branch RETURN --excel --sheet-per-var -o multi.xlsx
"""

import os
import sys
import argparse

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------
try:
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False

# ---------------------------------------------------------------------------
# Ensure sibling modules are importable (same scripts/ directory)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from fast_plotter import FastTPLPlotter
from fast_ppl_plotter import FastPPLPlotter


class DataExporter:
    """Export OLGA .tpl or .ppl results to DataFrame, CSV, or Excel.

    Parameters
    ----------
    file_path : str
        Absolute (or relative) path to a .tpl or .ppl file.
        File type is determined from the extension.
    """

    def __init__(self, file_path: str):
        if not _PANDAS_OK:
            raise ImportError(
                'pandas is required but not installed. '
                'Run: pip install pandas openpyxl'
            )

        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.tpl':
            self._mode = 'tpl'
        elif ext == '.ppl':
            self._mode = 'ppl'
        else:
            raise ValueError(
                'Unsupported file extension "%s". Expected .tpl or .ppl.' % ext
            )

        self.file_path = os.path.abspath(file_path)
        if not os.path.isfile(self.file_path):
            raise FileNotFoundError('File not found: %s' % self.file_path)

        self._plotter = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_tpl_plotter(self, variables, branch):
        """Return a FastTPLPlotter loaded for the requested (variables, branch)."""
        wanted_v = set(variables) if variables else None
        wanted_b = {branch} if branch else None
        # max_pts=0 disables downsampling so we get all time points
        return FastTPLPlotter(
            self.file_path,
            max_pts=999999,
            wanted_branches=wanted_b,
            wanted_vars=wanted_v,
        )

    def _get_ppl_plotter(self, variables, branch):
        """Return a FastPPLPlotter loaded for the requested (variables, branch)."""
        wanted_v = set(variables) if variables else None
        wanted_b = {branch} if branch else None
        return FastPPLPlotter(
            self.file_path,
            wanted_branches=wanted_b,
            wanted_vars=wanted_v,
        )

    def _resolve_tpl_branch(self, plotter, branch):
        """Return branch name, auto-detecting the first available if None."""
        if branch is not None:
            return branch
        available = plotter.available_branches()
        if not available:
            raise ValueError('No branches found in TPL file.')
        return available[0]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def to_dataframe(self, variables, branch=None, timestep=None):
        """Extract data into a pandas DataFrame.

        Parameters
        ----------
        variables : list[str]
            Variable names to extract (e.g. ['PT', 'HOL']).
        branch : str | None
            Branch name. For TPL: auto-detects first branch when None.
            For PPL: required.
        timestep : float | None
            PPL only. Timestep in seconds. None = last available.

        Returns
        -------
        pd.DataFrame
            TPL: index=time (s), columns=variables.
            PPL: index=position (m), columns=variables.
        """
        if not _PANDAS_OK:
            raise ImportError(
                'pandas is required. Run: pip install pandas openpyxl'
            )

        if self._mode == 'tpl':
            return self._tpl_to_dataframe(variables, branch)
        else:
            return self._ppl_to_dataframe(variables, branch, timestep)

    def _tpl_to_dataframe(self, variables, branch):
        plotter = self._get_tpl_plotter(variables, branch)
        branch = self._resolve_tpl_branch(plotter, branch)

        time_arr = plotter.time
        data = {}
        for var in variables:
            _, vals = plotter.get(var, branch)
            if vals is None:
                print('WARNING: variable "%s" not found for branch "%s", skipping.' % (
                    var, branch))
                continue
            data[var] = vals

        if not data:
            raise ValueError(
                'None of the requested variables found for branch "%s".' % branch
            )

        import numpy as np
        df = pd.DataFrame(data, index=time_arr)
        df.index.name = 'time_s'
        return df

    def _ppl_to_dataframe(self, variables, branch, timestep):
        if branch is None:
            raise ValueError('branch must be specified for PPL files.')

        plotter = self._get_ppl_plotter(variables, branch)

        # Resolve timestep: None -> last available
        all_ts = plotter.list_timesteps()
        if not all_ts:
            raise ValueError('No timesteps found in PPL file.')

        if timestep is None:
            actual_ts = float(all_ts[-1])
        else:
            import numpy as np
            ts_arr = [float(t) for t in all_ts]
            idx = int(min(range(len(ts_arr)), key=lambda i: abs(ts_arr[i] - timestep)))
            actual_ts = ts_arr[idx]

        data = {}
        positions = None
        for var in variables:
            pos, vals = plotter.get_profile(var, branch, timestep=actual_ts)
            if pos is None:
                print('WARNING: variable "%s" not found for branch "%s", skipping.' % (
                    var, branch))
                continue
            if positions is None:
                positions = pos
            data[var] = vals

        if not data:
            raise ValueError(
                'None of the requested variables found for branch "%s".' % branch
            )

        df = pd.DataFrame(data, index=positions)
        df.index.name = 'position_m'
        return df

    def to_csv(self, variables, branch=None, output=None, timestep=None):
        """Export to CSV.

        Parameters
        ----------
        variables : list[str]
        branch : str | None
        output : str | None
            Output file path. If None, derives from input filename.
        timestep : float | None
            PPL only.

        Returns
        -------
        str
            Absolute path to the written CSV file.
        """
        df = self.to_dataframe(variables, branch=branch, timestep=timestep)

        if output is None:
            base = os.path.splitext(self.file_path)[0]
            output = base + '.csv'
        output = os.path.abspath(output)

        df.to_csv(output, encoding='utf-8-sig')
        print('Saved CSV: %s  (%d rows x %d cols)' % (
            output, len(df), len(df.columns)))
        return output

    def to_excel(self, variables, branch=None, output=None,
                 sheet_per_var=False, timestep=None):
        """Export to Excel (.xlsx).

        Parameters
        ----------
        variables : list[str]
        branch : str | None
        output : str | None
            Output file path. If None, derives from input filename.
        sheet_per_var : bool
            If True, write one sheet per variable; otherwise one sheet 'data'.
        timestep : float | None
            PPL only.

        Returns
        -------
        str
            Absolute path to the written XLSX file, or CSV fallback path.
        """
        try:
            import openpyxl  # noqa: F401
            _openpyxl_ok = True
        except ImportError:
            _openpyxl_ok = False

        if not _openpyxl_ok:
            print('WARNING: openpyxl not installed. Falling back to CSV.')
            print('  To enable Excel export run: pip install openpyxl')
            if output:
                csv_out = os.path.splitext(output)[0] + '.csv'
            else:
                csv_out = None
            return self.to_csv(variables, branch=branch, output=csv_out,
                               timestep=timestep)

        df = self.to_dataframe(variables, branch=branch, timestep=timestep)

        if output is None:
            base = os.path.splitext(self.file_path)[0]
            output = base + '.xlsx'
        output = os.path.abspath(output)

        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if sheet_per_var:
                for col in df.columns:
                    sheet_df = df[[col]]
                    # Sheet names max 31 chars, sanitize slashes
                    sheet_name = str(col)[:31].replace('/', '_').replace('\\', '_')
                    sheet_df.to_excel(writer, sheet_name=sheet_name)
                print('Saved Excel: %s  (%d sheets)' % (output, len(df.columns)))
            else:
                df.to_excel(writer, sheet_name='data')
                print('Saved Excel: %s  (%d rows x %d cols)' % (
                    output, len(df), len(df.columns)))

        return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    # Windows cp949 safety: replace unencodable chars instead of crashing
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(errors='replace')

    ap = argparse.ArgumentParser(
        description='Export OLGA .tpl/.ppl results to CSV or Excel')
    ap.add_argument('file', help='Path to .tpl or .ppl file')
    ap.add_argument('--variables', required=True,
                    help='Comma-separated variable names (e.g. PT,HOL)')
    ap.add_argument('--branch', default=None,
                    help='Branch name (TPL: auto-detects first if omitted)')
    ap.add_argument('--timestep', type=float, default=None,
                    help='PPL only: timestep in seconds (default: last available)')
    ap.add_argument('--excel', action='store_true',
                    help='Export to Excel (.xlsx) instead of CSV')
    ap.add_argument('--sheet-per-var', action='store_true',
                    help='Excel only: one sheet per variable')
    ap.add_argument('-o', '--output', default=None,
                    help='Output file path (default: derived from input filename)')
    args = ap.parse_args()

    if not _PANDAS_OK:
        print('ERROR: pandas is required. Run: pip install pandas openpyxl')
        sys.exit(2)

    file_path = os.path.abspath(args.file)
    if not os.path.isfile(file_path):
        print('ERROR: file not found: %s' % file_path)
        sys.exit(2)

    variables = [v.strip() for v in args.variables.split(',') if v.strip()]
    if not variables:
        print('ERROR: --variables must not be empty')
        sys.exit(2)

    try:
        exp = DataExporter(file_path)
    except (ValueError, FileNotFoundError, ImportError) as e:
        print('ERROR: %s' % e)
        sys.exit(2)

    try:
        if args.excel:
            exp.to_excel(
                variables,
                branch=args.branch,
                output=args.output,
                sheet_per_var=args.sheet_per_var,
                timestep=args.timestep,
            )
        else:
            exp.to_csv(
                variables,
                branch=args.branch,
                output=args.output,
                timestep=args.timestep,
            )
    except (ValueError, FileNotFoundError) as e:
        print('ERROR: %s' % e)
        sys.exit(1)
    except Exception as e:
        print('ERROR: unexpected error: %s' % e)
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
