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

# pyfas pulls in pandas, which costs seconds to import. It is loaded only when a .tpl
# is read, or when a .ppl needs something the single-pass reader below does not do.
Tpl = Ppl = None


def _check_pyfas():
    global Tpl, Ppl
    if Tpl is None or Ppl is None:
        try:
            from pyfas import Tpl as _Tpl, Ppl as _Ppl
        except ImportError as exc:
            raise ImportError(
                "pyfas not installed. Run: pip install pyfas easydict"
            ) from exc
        Tpl, Ppl = _Tpl, _Ppl


def _float_tokens(line: str) -> list:
    """The numbers on one line, split on single spaces; anything else is skipped (as pyfas does)."""
    points = []
    for point in line.split(" "):
        try:
            points.append(float(point))
        except ValueError:
            pass
    return points


def _safe_key(key) -> str:
    """The key pyfas's ``data_in_df`` gives a branch or variable name."""
    key = str(key)
    if re.match(r"^\d", key):
        key = f"BRANCH_{key}"
    key = re.sub(r"[^a-zA-Z0-9_]", "_", key)
    return key or "EMPTY_KEY"


class _PplUnsupported(Exception):
    """The single-pass reader cannot answer this the way pyfas would; use pyfas."""


def _branches_in_catalog_order(profiles: dict) -> list[str]:
    """Each branch once, in the order the catalog first names it. pyfas used a set, whose
    order follows the hash seed, so the default branch changed from one start to the next."""
    named = (_SinglePassPpl._branch_of(line) for _idx, line in sorted(profiles.items()))
    return [branch for branch in dict.fromkeys(named) if branch]


class _SinglePassPpl:
    """Reads a .ppl once and extracts a variable only when asked.

    ``pyfas.Ppl`` re-reads the whole file for every catalog line and every branch while it
    initialises (and builds a DataFrame for every variable), so a 1 MB file with a few
    thousand variables took 35-70 s before anything was asked. The catalog, the time
    vector, and the geometries are the same few lines here; a variable's profile is parsed
    from the in-memory lines on demand. It follows pyfas's parsing rules line for line so
    the numbers are identical, except that a branch is matched by its whole name. Anything it does not cover is answered by pyfas, loaded on
    first use.
    """

    def __init__(self, fname: str):
        if not fname.endswith(".ppl"):
            raise ValueError("not a ppl file")
        self.abspath = fname
        with open(fname) as fobj:
            lines = fobj.readlines()
        self._lines = lines
        catalog = nvar_idx = data_idx = None
        self.profiles = {}
        branch_idx = []
        for idx, line in enumerate(lines):
            if "CATALOG" in line:
                catalog = idx
                nvar_idx = idx + 1
            if "TIME SERIES" in line:
                data_idx = idx
                break
            if catalog is not None:
                adj_idx = idx - catalog - 1
                if adj_idx > 0:
                    self.profiles[adj_idx] = line
            if "BRANCH\n" in line:
                branch_idx.append(idx + 1)
        if catalog is None or data_idx is None:
            raise _PplUnsupported("no catalog or time series section")
        self._catalog_idx = catalog
        self._data_idx = data_idx
        self._nvar = int(lines[nvar_idx])
        self.time = [float(line) for line in lines[1 + data_idx::self._nvar + 1]]
        self.geometries = {}
        for begin in branch_idx:
            self._extract_geometry(lines[begin].replace("'", "").replace("\n", ""), begin + 2)
        self._all_branches = _branches_in_catalog_order(self.profiles)
        self._legacy = None

    # -- what pyfas.Ppl offers, answered from the lines already in memory --------------

    @staticmethod
    def _branch_of(line: str):
        parts = line.split("'BRANCH:'")
        if len(parts) > 1:
            branch_part = parts[1].strip()
            return branch_part.split("'")[1] if "'" in branch_part else None
        return None

    def _extract_geometry(self, branch: str, begin: int) -> None:
        raw = []
        lines = self._lines
        for pos in range(begin, len(lines)):
            raw.extend(_float_tokens(lines[pos]))
            if re.search(r"[A-DF-Z]", lines[pos]) is not None:
                break
        self.geometries[branch] = (raw[:int(len(raw) / 2)], raw[int(len(raw) / 2):])

    def filter_data(self, pattern: str = "") -> dict:
        found = {}
        for idx in range(self._catalog_idx + 2, self._data_idx):
            line = self._lines[idx]
            if pattern in line:
                found[idx - self._catalog_idx - 1] = line
        return found

    @property
    def branches(self):
        return self._all_branches

    @property
    def timesteps(self):
        return self.time

    def extract(self, variable_idx: int):
        """``(x, [one list of values per timestep])`` for one catalog line."""
        branch = re.findall(r"'(.+?)'", self.profiles[variable_idx])[2]
        per_step = [_float_tokens(line)
                    for line in self._lines[variable_idx + 1 + self._data_idx::self._nvar + 1]]
        x_st = self.geometries[branch][0]
        if len(per_step[0]) == len(x_st):
            return list(x_st), per_step
        return [(x0 + x1) / 2 for x0, x1 in zip(x_st[:-1], x_st[1:])], per_step

    def profile_columns(self, variable: str, branch: str):
        """One variable on exactly one branch: ``(x, [values per timestep], catalog line)``.

        A branch is asked for by its own name or by the key ``data_in_df`` gives it (see
        ``_safe_key``). Its variables are the catalog lines of that branch only; pyfas takes
        every line that contains the name, so LINE_3 answers with LINE_3-10's values.
        """
        owner = self.branch_name(branch)
        props = {}
        for idx, line in self.profiles.items():
            if self._branch_of(line) == owner:
                props[line.split(" ")[0].strip()] = idx  # the last catalog line of a name wins
        variables = {}
        for raw_name in props:
            variables[_safe_key(raw_name)] = props[raw_name]
        if variable not in variables:
            raise ValueError(
                f"Variable '{variable}' not found in branch '{branch}'. Available: {list(variables)}"
            )
        x, per_step = self.extract(variables[variable])
        if (
            len(set(self.time)) != len(self.time)
            or len(per_step) != len(self.time)
            or len({len(step) for step in per_step}) != 1
            or len(per_step[0]) != len(x)
        ):
            raise _PplUnsupported("ragged profile")
        return x, per_step, self.profiles[variables[variable]]

    def branch_name(self, branch: str) -> str:
        """The catalog's own name for the branch asked for."""
        if branch in self._all_branches:
            return branch
        keyed = {}
        for raw_branch in self._all_branches:
            keyed.setdefault(_safe_key(raw_branch), []).append(raw_branch)
        if branch not in keyed:
            raise ValueError(f"Branch '{branch}' not found. Available: {list(keyed)}")
        if len(keyed[branch]) > 1:
            raise ValueError(f"Branch '{branch}' fits more than one branch: {sorted(keyed[branch])}. Ask for one of them.")
        return keyed[branch][0]

    # -- everything else is pyfas's -----------------------------------------------------

    @property
    def legacy(self):
        if self._legacy is None:
            _check_pyfas()
            self._legacy = Ppl(self.abspath)
        return self._legacy

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.legacy, name)


def _to_list(arr) -> list:
    """Convert numpy array or list to a JSON-serializable Python list.
    NaN and Inf values are converted to None (JSON null)."""
    if arr is None:
        return []
    if not isinstance(arr, (list, tuple)):  # a list needs no numpy (and its import time)
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

    kind = ""
    for token in quoted:
        if token.startswith("(") and token.endswith(")"):
            unit = token[1:-1]  # strip parens
        elif token == "BRANCH:" and not position:
            kind = ""  # "'BOUNDARY:' 'BRANCH:' 'LINE'" in a .ppl: the label is the branch itself
        elif token in ("POSITION:", "SECTION:", "BRANCH:"):
            continue
        elif not position and not kind and token.endswith(":"):
            # Another kind word (CONTROLLER:, VALVE:, NODE:, ...): the label after it is the
            # position, named "<KIND> - <label>" as the trend catalog lists it.
            kind = token[:-1]
        elif not position:
            position = f"{kind} - {token}" if kind else token
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
        self.filepath = os.path.abspath(filepath)

        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".tpl":
            _check_pyfas()
            self.file_type = "tpl"
            self._reader = Tpl(self.filepath)
        elif ext == ".ppl":
            self.file_type = "ppl"
            try:
                self._reader = _SinglePassPpl(self.filepath)
            except Exception:
                # Anything the single-pass reader cannot take is pyfas's to read, or to reject.
                _check_pyfas()
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
        if isinstance(self._reader, _SinglePassPpl):
            return list(self._reader.branches)
        return _branches_in_catalog_order(self._reader.profiles)

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

        reader = self._reader
        if isinstance(reader, _SinglePassPpl):
            try:
                return self._get_profile_single_pass(reader, variable, branch, timestep)
            except _PplUnsupported:
                owner = reader.branch_name(branch)
                if any(other and other != owner and (owner in other or _safe_key(other) == _safe_key(owner))
                       for other in reader.branches):
                    raise ValueError(f"The profile of '{variable}' on branch '{owner}' is incomplete in this file.")
                reader, branch = reader.legacy, _safe_key(owner)
        data_in_df = reader.data_in_df
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
        timesteps = list(reader.timesteps)

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
        unit = self._catalog_unit(reader, variable, branch)

        return {
            "variable": variable,
            "branch": branch,
            "timestep": float(col),
            "timestep_unit": "s",
            "positions": _to_list(list(profile_series.index)),
            "values": _to_list(list(profile_series.values)),
            "unit": unit,
        }

    @staticmethod
    def _catalog_unit(reader, variable: str, branch: str) -> str:
        """The unit the catalog gives the first line of ``variable`` on ``branch``.

        Both names are matched whole, by their own spelling or the key ``data_in_df`` gives
        them, so LINE_1 finds 'LINE-1' and never 'LINE-10'.
        """
        for _, raw_line in sorted(reader.filter_data(variable).items()):
            name = raw_line.split(" ")[0].strip()
            owner = _SinglePassPpl._branch_of(raw_line)
            if variable not in (name, _safe_key(name)) or owner is None:
                continue
            if branch in (owner, _safe_key(owner)):
                return _parse_catalog_line(raw_line)["unit"]
        return ""

    def _get_profile_single_pass(self, reader, variable: str, branch: str, timestep: Optional[float]) -> dict:
        """``get_profile`` for a .ppl read by ``_SinglePassPpl``: parses only this variable."""
        x, per_step, catalog_line = reader.profile_columns(variable, branch)
        timesteps = list(reader.timesteps)
        if timestep is None:
            index = len(timesteps) - 1
        else:
            index = min(range(len(timesteps)), key=lambda i: abs(timesteps[i] - timestep))
        return {
            "variable": variable,
            "branch": branch,
            "timestep": float(timesteps[index]),
            "timestep_unit": "s",
            "positions": _to_list(x),
            "values": _to_list(per_step[index]),
            "unit": _parse_catalog_line(catalog_line)["unit"],
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
        "--index",
        action="store_true",
        help="All of a file's lists in one JSON answer (variables, and branches/timesteps or the time range)",
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

    # --index: one start of this script answers everything a load asks
    if args.index:
        index = {"variables": rp.list_variables()}
        if rp.file_type == "ppl":
            index["branches"] = rp.list_branches()
            index["timesteps"] = rp.list_timesteps()
        elif index["variables"]:
            try:
                time = rp.get_time_series(index["variables"][0]["variable"])["time"]
            except Exception:  # the variables are still worth listing
                time = []
            if time:
                index["time_range"] = {"start_s": time[0], "end_s": time[-1], "samples": len(time)}
        print(json.dumps(index))
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
