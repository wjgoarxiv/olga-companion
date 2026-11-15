"""
result_parser.py — OLGA result file parser wrapping pyfas

Supports .tpl (trend/time-series) and .ppl (profile/spatial) OLGA output files.

Usage:
    python result_parser.py <file.tpl|.ppl> [--variable PT] [--list-vars] [--json]

Examples:
    python result_parser.py results.tpl --list-vars
    python result_parser.py results.tpl --variable PT --json
    python result_parser.py results.ppl --list-vars
    python result_parser.py results.ppl --variable PT --json
"""

import json
import math
import os
import re
import sys
from typing import Optional

try:
    from pyfas import Tpl, Ppl
    PYFAS_AVAILABLE = True
except ImportError:
    PYFAS_AVAILABLE = False


def _check_pyfas():
    if not PYFAS_AVAILABLE:
        raise ImportError(
            "pyfas not installed. Run: pip install pyfas easydict"
        )


def _to_list(arr) -> list:
    """Convert numpy array or list to a JSON-serializable Python list.
    NaN and Inf values are converted to None (JSON null)."""
    if arr is None:
        return []
    try:
        import numpy as np
        if isinstance(arr, np.ndarray):
            arr = arr.tolist()
    except ImportError:
        pass
    if isinstance(arr, (list, tuple)):
        return [None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v
                for v in arr]
    return list(arr)


def _parse_catalog_line(raw_line: str) -> dict:
    """Parse a raw catalog line into structured fields.

    Tpl format:  PT 'POSITION:' 'TIEIN' '(Pa)' 'Pressure'
    Ppl format:  PT 'SECTION:' 'BRANCH:' 'riser' '(Pa)' 'Pressure'
    """
    raw = raw_line.strip()
    parts = raw.split()
    variable = parts[0] if parts else ""

    # Extract all single-quoted tokens
    quoted = re.findall(r"'([^']*)'", raw)

    unit = ""
    description = ""
    position = ""

    for token in quoted:
        if token.startswith("(") and token.endswith(")"):
            unit = token[1:-1]  # strip parens
        elif token in ("POSITION:", "SECTION:", "BRANCH:"):
            continue
        elif not position and token not in ("POSITION:", "SECTION:", "BRANCH:"):
            position = token
        elif position and not description:
            description = token

    return {
        "variable": variable,
        "position": position,
        "unit": unit,
        "description": description,
        "raw": raw,
    }


def _only_variable(matches: dict, variable: str) -> dict:
    """Keep the catalog lines for exactly ``variable``: pyfas filters by
    substring, so HOL also lists HOLHL and HOLWT."""
    wanted = variable.strip().upper()
    return {k: v for k, v in matches.items() if _parse_catalog_line(v)["variable"].upper() == wanted}


def _select_position(matches: dict, position: str) -> int:
    """Pick the catalog index whose position is exactly ``position``.

    POS_MAIN never resolves to POS_MAIN_1; any other position is refused.
    """
    wanted = position.strip().upper()
    exact = [k for k, v in matches.items() if _parse_catalog_line(v)["position"].upper() == wanted]
    if exact:
        return exact[0]
    names = sorted({_parse_catalog_line(v)["position"] for v in matches.values()})
    raise ValueError(f"Position '{position}' is not one of: {', '.join(names)}.")


class ResultParser:
    """Parse OLGA .tpl and .ppl output files via pyfas.

    Auto-detects file type from extension.

    Parameters
    ----------
    filepath : str
        Path to a .tpl or .ppl file.
    """

    def __init__(self, filepath: str):
        _check_pyfas()
        self.filepath = os.path.abspath(filepath)

        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".tpl":
            self.file_type = "tpl"
            self._reader = Tpl(self.filepath)
        elif ext == ".ppl":
            self.file_type = "ppl"
            self._reader = Ppl(self.filepath)
        else:
            raise ValueError(
                f"Unsupported file extension '{ext}'. Expected .tpl or .ppl."
            )

    @property
    def is_tpl(self) -> bool:
        """True for trend (.tpl) files, False for profile (.ppl) files."""
        return self.file_type == "tpl"

    @property
    def is_ppl(self) -> bool:
        return self.file_type == "ppl"

    def _ensure_trends_extracted(self):
        if self.file_type == "tpl":
            all_idx = list(self._reader.trends.keys())
            if all_idx:
                self._reader.extract(*all_idx)

    @property
    def trend_data(self):
        """idx -> extracted values for every trend (``.tpl`` only)."""
        if self.file_type != "tpl":
            return {}
        self._ensure_trends_extracted()
        return getattr(self._reader, "data", {}) or {}

    @property
    def time(self):
        """Time vector; pyfas populates it only after an extract() call."""
        reader = self._reader
        tvec = getattr(reader, "time", None)
        if tvec is None or len(_to_list(tvec)) == 0:
            self._ensure_trends_extracted()
        return getattr(reader, "time", [])

    def __getattr__(self, name: str):
        """Delegate unknown attributes to the underlying pyfas reader.

        Lets callers reach reader fields (time, data, trends, geometries,
        timesteps, ...) directly through the parser without hand-listing each
        proxy. Only consulted for attributes missing on the instance/class.
        """
        reader = self.__dict__.get("_reader")
        if reader is not None and hasattr(reader, name):
            return getattr(reader, name)
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}"
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _tpl_df_to_variable_list(self, df) -> list[dict]:
        """Convert a view_trends DataFrame to a list of dicts."""
        records = []
        for _, row in df.iterrows():
            records.append({
                "index": int(row["Index"]),
                "variable": str(row["Variable"]),
                "position": str(row["Position"]),
                "unit": str(row["Unit"]),
                "description": str(row.get("Description", "")),
            })
        return records

    # ------------------------------------------------------------------
    # TPL methods
    # ------------------------------------------------------------------

    def list_variables(self) -> list[dict]:
        """List all available variables.

        Returns
        -------
        list of dict
            For .tpl: each dict has keys ``index``, ``variable``, ``position``,
            ``unit``, ``description``.
            For .ppl: each dict has keys ``variable``, ``branches``, ``unit``,
            ``description``.
        """
        if self.file_type == "tpl":
            df = self._reader.view_trends("")
            return self._tpl_df_to_variable_list(df)
        else:
            return self._ppl_list_variables()

    def get_time_series(self, variable: str, position: Optional[str] = None) -> dict:
        """Extract time series for a variable from a .tpl file.

        Parameters
        ----------
        variable : str
            OLGA variable name, e.g. ``"PT"``.
        position : str, optional
            Position label to narrow the match when multiple positions exist,
            e.g. ``"INLET"``.

        Returns
        -------
        dict with keys: ``variable``, ``position``, ``unit``, ``time``,
        ``values``, ``time_unit``, ``index``.

        Raises
        ------
        ValueError
            If file is not .tpl or the variable is not found.
        """
        if self.file_type != "tpl":
            raise ValueError("get_time_series() is only available for .tpl files.")

        matches = _only_variable(self._reader.filter_trends(variable), variable)
        if not matches:
            raise ValueError(f"Variable '{variable}' not found in {self.filepath}.")

        if position:
            idx = _select_position(matches, position)
            raw_line = matches[idx]
        else:
            idx, raw_line = next(iter(matches.items()))
        parsed = _parse_catalog_line(raw_line)

        self._reader.extract(idx)

        return {
            "variable": parsed["variable"],
            "position": parsed["position"],
            "unit": parsed["unit"],
            "description": parsed["description"],
            "index": idx,
            "time": _to_list(self._reader.time),
            "values": _to_list(self._reader.data[idx]),
            "time_unit": "s",
        }

    def get_all_variables(self) -> dict:
        """Extract all trend data from a .tpl file.

        Returns
        -------
        dict
            Keys are variable indices (int). Each value is a dict matching
            the structure returned by :meth:`get_time_series`.

        Raises
        ------
        ValueError
            If file is not .tpl.
        """
        if self.file_type != "tpl":
            raise ValueError("get_all_variables() is only available for .tpl files.")

        all_idx = list(self._reader.trends.keys())
        if not all_idx:
            return {}

        self._reader.extract(*all_idx)

        result = {}
        for idx in all_idx:
            raw_line = self._reader.trends[idx]
            parsed = _parse_catalog_line(raw_line)
            result[idx] = {
                "variable": parsed["variable"],
                "position": parsed["position"],
                "unit": parsed["unit"],
                "description": parsed["description"],
                "index": idx,
                "time": _to_list(self._reader.time),
                "values": _to_list(self._reader.data.get(idx, [])),
                "time_unit": "s",
            }
        return result

    # ------------------------------------------------------------------
    # PPL methods
    # ------------------------------------------------------------------

    def _ppl_list_variables(self) -> list[dict]:
        """Build variable list from ppl.filter_data."""
        all_raw = self._reader.filter_data("")
        seen = {}
        for idx, raw_line in all_raw.items():
            parsed = _parse_catalog_line(raw_line)
            var = parsed["variable"]
            if var not in seen:
                seen[var] = {
                    "variable": var,
                    "branches": [],
                    "unit": parsed["unit"],
                    "description": parsed["description"],
                }
            branch = parsed["position"]
            if branch and branch not in seen[var]["branches"]:
                seen[var]["branches"].append(branch)
        return list(seen.values())

    def list_branches(self) -> list[str]:
        """List all branch names in a .ppl file.

        Raises
        ------
        ValueError
            If file is not .ppl.
        """
        if self.file_type != "ppl":
            raise ValueError("list_branches() is only available for .ppl files.")
        return list(self._reader.branches)

    def list_timesteps(self) -> list[float]:
        """List all available timesteps (seconds) in a .ppl file.

        Raises
        ------
        ValueError
            If file is not .ppl.
        """
        if self.file_type != "ppl":
            raise ValueError("list_timesteps() is only available for .ppl files.")
        return list(self._reader.timesteps)

    def get_profile(
        self,
        variable: str,
        branch: str,
        timestep: Optional[float] = None,
    ) -> dict:
        """Get a spatial profile from a .ppl file.

        Parameters
        ----------
        variable : str
            OLGA variable name, e.g. ``"PT"``.
        branch : str
            Branch name, e.g. ``"riser"``.
        timestep : float, optional
            Exact timestep in seconds. If None, the last available timestep is
            used. If the exact value is not a column, the nearest timestep is
            selected.

        Returns
        -------
        dict with keys: ``variable``, ``branch``, ``timestep``, ``positions``,
        ``values``, ``unit``.

        Raises
        ------
        ValueError
            If file is not .ppl, or branch/variable not found.
        """
        if self.file_type != "ppl":
            raise ValueError("get_profile() is only available for .ppl files.")

        data_in_df = self._reader.data_in_df
        if branch not in data_in_df:
            available = list(data_in_df.keys())
            raise ValueError(
                f"Branch '{branch}' not found. Available: {available}"
            )

        branch_data = data_in_df[branch]
        if variable not in branch_data:
            available = list(branch_data.keys())
            raise ValueError(
                f"Variable '{variable}' not found in branch '{branch}'. "
                f"Available: {available}"
            )

        df = branch_data[variable]
        timesteps = list(self._reader.timesteps)

        if timestep is None:
            selected_t = timesteps[-1] if timesteps else df.columns[-1]
        else:
            # Find nearest timestep
            import numpy as np
            ts_arr = np.array(timesteps)
            idx = int(np.argmin(np.abs(ts_arr - timestep)))
            selected_t = timesteps[idx]

        # Resolve column — df.columns are floats
        col = selected_t
        if col not in df.columns:
            # Find nearest column
            import numpy as np
            cols = np.array(df.columns, dtype=float)
            col = float(df.columns[int(np.argmin(np.abs(cols - col)))])

        profile_series = df[col]

        # Resolve unit from catalog
        unit = ""
        raw_entries = self._reader.filter_data(variable)
        for _, raw_line in raw_entries.items():
            if branch.lower() in raw_line.lower():
                parsed = _parse_catalog_line(raw_line)
                unit = parsed["unit"]
                break

        return {
            "variable": variable,
            "branch": branch,
            "timestep": float(col),
            "timestep_unit": "s",
            "positions": _to_list(list(profile_series.index)),
            "values": _to_list(list(profile_series.values)),
            "unit": unit,
        }

    def get_geometry(self, branch: str) -> dict:
        """Get branch geometry (x and y coordinates).

        Parameters
        ----------
        branch : str
            Branch name.

        Returns
        -------
        dict with keys: ``branch``, ``x`` (horizontal distance in m),
        ``y`` (elevation in m).

        Raises
        ------
        ValueError
            If file is not .ppl or branch not found.
        """
        if self.file_type != "ppl":
            raise ValueError("get_geometry() is only available for .ppl files.")

        geometries = self._reader.geometries
        if branch not in geometries:
            available = list(geometries.keys())
            raise ValueError(
                f"Branch '{branch}' not found. Available: {available}"
            )

        geo = geometries[branch]
        return {
            "branch": branch,
            "x": _to_list(geo[0]),
            "y": _to_list(geo[1]),
        }

    # ------------------------------------------------------------------
    # Common export methods
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return all parsed data as a JSON-serializable dict.

        For .tpl files, extracts all trend variables.
        For .ppl files, extracts all profiles for all branches and variables.
        """
        if self.file_type == "tpl":
            return {
                "file_type": "tpl",
                "filepath": self.filepath,
                "variables": self.get_all_variables(),
            }
        else:
            branches = self.list_branches()
            timesteps = self.list_timesteps()
            variables_meta = self.list_variables()

            profiles = {}
            for branch in branches:
                profiles[branch] = {
                    "geometry": self.get_geometry(branch),
                    "profiles": {},
                }
                branch_data = self._reader.data_in_df.get(branch, {})
                for var in branch_data:
                    var_profiles = []
                    for ts in timesteps:
                        try:
                            p = self.get_profile(var, branch, timestep=ts)
                            var_profiles.append(p)
                        except Exception:
                            pass
                    profiles[branch]["profiles"][var] = var_profiles

            return {
                "file_type": "ppl",
                "filepath": self.filepath,
                "branches": branches,
                "timesteps": timesteps,
                "variables": variables_meta,
                "data": profiles,
            }

    def to_json(self, indent: int = 2) -> str:
        """Serialize all parsed data to a JSON string.

        Parameters
        ----------
        indent : int
            JSON indentation level (default: 2).
        """
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    import argparse

    parser = argparse.ArgumentParser(
        description="Parse OLGA .tpl or .ppl result files using pyfas.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("file", help="Path to .tpl or .ppl file")
    parser.add_argument(
        "--variable", "-v",
        metavar="VAR",
        help="Variable name to extract (e.g. PT, TM, HOL)",
    )
    parser.add_argument(
        "--position", "-p",
        metavar="POS",
        help="Position label filter for .tpl (e.g. INLET, EXIT)",
    )
    parser.add_argument(
        "--branch", "-b",
        metavar="BRANCH",
        help="Branch name for .ppl profile extraction",
    )
    parser.add_argument(
        "--timestep", "-t",
        type=float,
        metavar="SECONDS",
        help="Timestep in seconds for .ppl profile (default: last timestep)",
    )
    # Set stdout to UTF-8 on Windows to avoid cp949 encoding errors
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    parser.add_argument(
        "--list-vars", "-l",
        action="store_true",
        help="List all available variables",
    )
    parser.add_argument(
        "--list-branches",
        action="store_true",
        help="List all branch names (.ppl only)",
    )
    parser.add_argument(
        "--list-timesteps",
        action="store_true",
        help="List all timesteps (.ppl only)",
    )
    parser.add_argument(
        "--geometry",
        metavar="BRANCH",
        help="Print geometry for a branch (.ppl only)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export all data as JSON",
    )

    args = parser.parse_args()

    try:
        rp = ResultParser(args.file)
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # --all
    if args.all:
        print(rp.to_json())
        return

    # --list-vars
    if args.list_vars:
        variables = rp.list_variables()
        if args.json:
            print(json.dumps(variables, indent=2))
        else:
            print(f"\nAvailable variables in {os.path.basename(args.file)}:\n")
            if rp.file_type == "tpl":
                print(f"{'Idx':>4}  {'Variable':<10}  {'Position':<25}  {'Unit':<10}  Description")
                print("-" * 75)
                for v in variables:
                    print(f"{v['index']:>4}  {v['variable']:<10}  {v['position']:<25}  {v['unit']:<10}  {v['description']}")
            else:
                print(f"{'Variable':<10}  {'Unit':<10}  {'Branches'}")
                print("-" * 60)
                for v in variables:
                    print(f"{v['variable']:<10}  {v['unit']:<10}  {', '.join(v['branches'])}")
        return

    # --list-branches (.ppl)
    if args.list_branches:
        if rp.file_type != "ppl":
            print("Error: --list-branches is only for .ppl files.", file=sys.stderr)
            sys.exit(1)
        branches = rp.list_branches()
        if args.json:
            print(json.dumps(branches, indent=2))
        else:
            print("\nBranches:")
            for b in branches:
                print(f"  {b}")
        return

    # --list-timesteps (.ppl)
    if args.list_timesteps:
        if rp.file_type != "ppl":
            print("Error: --list-timesteps is only for .ppl files.", file=sys.stderr)
            sys.exit(1)
        timesteps = rp.list_timesteps()
        if args.json:
            print(json.dumps(timesteps, indent=2))
        else:
            print("\nTimesteps (s):")
            for t in timesteps:
                print(f"  {t}")
        return

    # --geometry BRANCH (.ppl)
    if args.geometry:
        if rp.file_type != "ppl":
            print("Error: --geometry is only for .ppl files.", file=sys.stderr)
            sys.exit(1)
        geo = rp.get_geometry(args.geometry)
        if args.json:
            print(json.dumps(geo, indent=2))
        else:
            print(f"\nGeometry for branch '{geo['branch']}':")
            print(f"  x (m): {geo['x'][:5]}{'...' if len(geo['x']) > 5 else ''}")
            print(f"  y (m): {geo['y'][:5]}{'...' if len(geo['y']) > 5 else ''}")
            print(f"  Points: {len(geo['x'])}")
        return

    # --variable VAR
    if args.variable:
        if rp.file_type == "tpl":
            data = rp.get_time_series(args.variable, position=args.position)
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                print(f"\nTime series: {data['variable']} @ {data['position']}")
                print(f"  Unit      : {data['unit']}")
                print(f"  Points    : {len(data['time'])}")
                if data['time']:
                    print(f"  Time range: {data['time'][0]:.1f} – {data['time'][-1]:.1f} s")
                    print(f"  Value range: {min(v for v in data['values'] if v is not None):.4g}"
                          f" – {max(v for v in data['values'] if v is not None):.4g} {data['unit']}")
        else:
            branch = args.branch or rp.list_branches()[0]
            data = rp.get_profile(args.variable, branch, timestep=args.timestep)
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                print(f"\nProfile: {data['variable']} in branch '{data['branch']}'")
                print(f"  Timestep  : {data['timestep']} s")
                print(f"  Unit      : {data['unit']}")
                print(f"  Nodes     : {len(data['positions'])}")
                if data['positions']:
                    print(f"  Position range: {data['positions'][0]:.1f} – {data['positions'][-1]:.1f} m")
                    valid_vals = [v for v in data['values'] if v is not None]
                    if valid_vals:
                        print(f"  Value range: {min(valid_vals):.4g} – {max(valid_vals):.4g} {data['unit']}")
        return

    # Default: print summary
    print(f"\nFile     : {rp.filepath}")
    print(f"Type     : {rp.file_type.upper()}")
    if rp.file_type == "tpl":
        variables = rp.list_variables()
        print(f"Variables: {len(variables)}")
        print("\nUse --list-vars to see all variables.")
        print("Use --variable PT to extract a time series.")
    else:
        branches = rp.list_branches()
        timesteps = rp.list_timesteps()
        variables = rp.list_variables()
        print(f"Branches : {len(branches)}")
        print(f"Timesteps: {len(timesteps)}")
        print(f"Variables: {len(variables)}")
        print("\nUse --list-vars, --list-branches, --list-timesteps for details.")
        print("Use --variable PT --branch riser to extract a profile.")


if __name__ == "__main__":
    _cli()
