"""
genkey_validator.py — Validation rule engine for OLGA .genkey simulation input files.

Usage:
    python genkey_validator.py <file.genkey>

Exit codes:
    0 — no errors found (warnings/info are OK)
    1 — one or more errors found
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import parser
# ---------------------------------------------------------------------------

try:
    from genkey_parser import GenkeyParser
except ImportError:
    # Allow running from a different working directory by adjusting sys.path
    sys.path.insert(0, str(Path(__file__).parent))
    from genkey_parser import GenkeyParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _numeric(val) -> float | None:
    """Extract a plain number from a parsed value (int, float, or {value, unit} dict)."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict) and "value" in val:
        v = val["value"]
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _as_list(val) -> list:
    """Ensure a value is returned as a list.

    Handles bare scalars, dicts with 'value' lists (tuples with units),
    and plain lists.
    """
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, dict) and "value" in val:
        v = val["value"]
        if isinstance(v, list):
            return v
        return [v]
    return [val]


def _label(params: dict, fallback: str = "") -> str:
    """Return LABEL string from a params dict, or fallback."""
    return str(params.get("LABEL", fallback))


# ---------------------------------------------------------------------------
# GenkeyValidator
# ---------------------------------------------------------------------------

class GenkeyValidator:
    """Validate a parsed .genkey file against a set of named rules.

    Parameters
    ----------
    parser : GenkeyParser
        A fully initialised GenkeyParser instance.
    """

    def __init__(self, parser: GenkeyParser):
        self.parser = parser
        self._findings: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self) -> list[dict]:
        """Run all validation rules and return findings list.

        Each finding is a dict with keys:
            rule_id, severity, category, message, location, suggestion
        """
        self._findings = []

        self._run_global_rules()
        self._run_topology_rules()
        self._run_boundary_rules()
        self._run_material_rules()
        self._run_physical_rules()
        self._run_timestep_rules()
        self._run_solver_syntax_rules()

        return self._findings

    def summary(self) -> str:
        """Return a human-readable validation report."""
        findings = self._findings if self._findings else self.validate()

        filename = Path(self.parser.filepath).name
        errors   = [f for f in findings if f["severity"] == "ERROR"]
        warnings = [f for f in findings if f["severity"] == "WARNING"]
        infos    = [f for f in findings if f["severity"] == "INFO"]

        width = max(len(filename) + 22, 40)
        header_line = "=" * width

        lines = [
            f"Validation Report: {filename}",
            header_line,
            f"ERRORS:   {len(errors)}",
            f"WARNINGS: {len(warnings)}",
            f"INFO:     {len(infos)}",
        ]

        def _section(title: str, bucket: list[dict]):
            if not bucket:
                return
            lines.append("")
            lines.append(title)
            lines.append("-" * len(title))
            for f in bucket:
                lines.append(f"[{f['rule_id']}] {f['message']}")
                if f.get("location"):
                    lines.append(f"       Location : {f['location']}")
                if f.get("suggestion"):
                    lines.append(f"       Suggestion: {f['suggestion']}")

        _section("ERRORS",   errors)
        _section("WARNINGS", warnings)
        _section("INFO",     infos)

        if not findings:
            lines.append("")
            lines.append("No issues found.")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Return JSON-serialisable result dict."""
        findings = self._findings if self._findings else self.validate()
        errors   = [f for f in findings if f["severity"] == "ERROR"]
        warnings = [f for f in findings if f["severity"] == "WARNING"]
        infos    = [f for f in findings if f["severity"] == "INFO"]
        return {
            "filepath": self.parser.filepath,
            "summary": {
                "errors":   len(errors),
                "warnings": len(warnings),
                "info":     len(infos),
                "total":    len(findings),
            },
            "findings": findings,
        }

    # ------------------------------------------------------------------
    # Internal: finding factory
    # ------------------------------------------------------------------

    def _add(
        self,
        rule_id: str,
        severity: str,
        category: str,
        message: str,
        location: str = "",
        suggestion: str = "",
    ):
        self._findings.append({
            "rule_id":    rule_id,
            "severity":   severity,
            "category":   category,
            "message":    message,
            "location":   location,
            "suggestion": suggestion,
        })

    # ------------------------------------------------------------------
    # X rules — Solver-syntax gates (catch cases OLGA rejects at
    # verification even though the topology/boundary rules pass). These
    # mirror the OLGA 2022.1.0 / 2025 verification errors and are
    # version-portable (all use the classic scalar keyword forms).
    # ------------------------------------------------------------------

    @staticmethod
    def _value_list(raw):
        """Return the numeric list behind a scalar, tuple, or {value,unit} dict."""
        if isinstance(raw, dict):
            raw = raw.get("value")
        if isinstance(raw, (list, tuple)):
            return list(raw)
        if raw is None:
            return []
        return [raw]

    @staticmethod
    def _is_numeric_tag(val):
        """True if a FLUID tag is a bare number (1, '1', 2.0) rather than a label."""
        if isinstance(val, bool):
            return False
        if isinstance(val, (int, float)):
            return True
        if isinstance(val, str):
            s = val.strip().strip('"').strip("'")
            try:
                float(s)
                return True
            except ValueError:
                return False
        return False

    def _is_adiabatic(self) -> bool:
        """True when OPTIONS asks for an adiabatic temperature model."""
        globals_ = getattr(self.parser, "global_keywords", None) or {}
        options = globals_.get("OPTIONS") if isinstance(globals_, dict) else None
        if not isinstance(options, dict):
            return False
        return str(options.get("TEMPERATURE", "")).strip().upper() == "ADIABATIC"

    def _run_solver_syntax_rules(self):
        walls     = self.parser.walls
        flowpaths = self.parser.flowpaths

        # X002: a stray LAYERS key on WALL. OLGA 2022.1.0 rejects it with
        # "Key not found. (LAYERS for WALL <label> in LIBRARY LIBRARY)"; the
        # layer count comes from the THICKNESS/MATERIAL tuple length. Tuple
        # THICKNESS itself is valid — a qualified production case runs with
        # `THICKNESS=(0.005) m, MATERIAL=("Steel")` and no LAYERS.
        for wall in walls:
            wlabel = str(wall.get("LABEL", "(unnamed)"))
            thk = self._value_list(wall.get("THICKNESS"))
            mat = _as_list(wall.get("MATERIAL"))
            if "LAYERS" in wall:
                self._add(
                    "X002", "ERROR", "solver-syntax",
                    f"WALL '{wlabel}' declares a LAYERS key; OLGA rejects it "
                    f"and derives the layer count from THICKNESS/MATERIAL",
                    location=f"WALL {wlabel}",
                    suggestion="Remove the LAYERS key",
                )
            if thk and mat and len(thk) != len(mat):
                self._add(
                    "X003", "ERROR", "solver-syntax",
                    f"WALL '{wlabel}' has {len(thk)} thickness(es) but "
                    f"{len(mat)} material(s); counts must match",
                    location=f"WALL {wlabel}",
                    suggestion="Give one MATERIAL per THICKNESS layer",
                )

        for fp in flowpaths:
            tag = fp.get("tag", "")
            children = fp.get("children", [])
            pipes = [c for c in children if c["keyword"] == "PIPE"]

            # X010: BRANCH FLUID must be a PVT-table label, not a bare number.
            for child in children:
                if child["keyword"] == "BRANCH":
                    fluid = child["params"].get("FLUID")
                    if fluid is not None and self._is_numeric_tag(fluid):
                        self._add(
                            "X010", "ERROR", "solver-syntax",
                            f"FLOWPATH '{tag}' BRANCH FLUID={fluid} is a bare "
                            f"number; OLGA needs the PVT table label",
                            location=f"{tag} / BRANCH",
                            suggestion='Set FLUID="<PVTTABLE label>" (see the .tab file)',
                        )

            # X011: HEATTRANSFER is required only when OLGA actually computes
            # wall/ambient heat transfer. An ADIABATIC case legitimately ships
            # none (proven by a qualified production case).
            if (
                pipes
                and not self._is_adiabatic()
                and not any(c["keyword"] == "HEATTRANSFER" for c in children)
            ):
                self._add(
                    "X011", "ERROR", "solver-syntax",
                    f"FLOWPATH '{tag}' has pipes and a non-adiabatic temperature "
                    f"model but no HEATTRANSFER keyword",
                    location=tag,
                    suggestion=(
                        "Add HEATTRANSFER ... HOUTEROPTION=HGIVEN, TAMBIENT=..., "
                        "HAMBIENT=... or set OPTIONS TEMPERATURE=ADIABATIC"
                    ),
                )

            # X012 / X013: LENGTH consistency and scalar ELEVATION.
            for pipe in pipes:
                params   = pipe["params"]
                pipe_lbl = str(params.get("LABEL", "(unnamed)"))
                loc      = f"{tag} / PIPE {pipe_lbl}"
                # LENGTH is optional when LSEGMENT describes the pipe (proven by
                # a qualified production case). What OLGA does reject is a
                # LENGTH that disagrees with the LSEGMENT sum.
                lsegments = self._value_list(params.get("LSEGMENT"))
                length = self._value_list(params.get("LENGTH"))
                if "LENGTH" in params and lsegments and len(length) == 1:
                    try:
                        declared = float(length[0])
                        summed = sum(float(value) for value in lsegments)
                    except (TypeError, ValueError):
                        declared = summed = None
                    if (
                        declared is not None
                        and summed
                        and abs(declared - summed) > max(0.01 * summed, 1e-6)
                    ):
                        self._add(
                            "X012", "ERROR", "solver-syntax",
                            f"PIPE '{pipe_lbl}' in '{tag}' declares LENGTH="
                            f"{declared:g} but its LSEGMENT sum is {summed:g}; "
                            f"OLGA rejects the mismatch (1% tolerance)",
                            location=loc,
                            suggestion="Make LENGTH equal the LSEGMENT sum, or drop LENGTH",
                        )
                elev = self._value_list(params.get("ELEVATION"))
                if len(elev) > 1:
                    self._add(
                        "X013", "ERROR", "solver-syntax",
                        f"PIPE '{pipe_lbl}' in '{tag}' gives {len(elev)} "
                        f"ELEVATION values; OLGA expects a single scalar",
                        location=loc,
                        suggestion="Use ELEVATION=<total rise> m (a scalar)",
                    )

    # ------------------------------------------------------------------
    # G rules — Global settings
    # ------------------------------------------------------------------

    def _run_global_rules(self):
        gk = self.parser.global_keywords

        # G001: OPTIONS must exist
        if "OPTIONS" not in gk:
            self._add(
                "G001", "ERROR", "global",
                "OPTIONS keyword is missing",
                location="(file level)",
                suggestion="Add an OPTIONS keyword with at least STEADYSTATE setting",
            )

        # G002: FILES must define PVTFILE
        if "FILES" not in gk:
            self._add(
                "G002", "ERROR", "global",
                "FILES keyword is missing; PVTFILE is required for fluid properties",
                location="(file level)",
                suggestion="Add FILES PVTFILE=\"path/to/fluid.tab\"",
            )
        else:
            files_params = gk["FILES"]
            if "PVTFILE" not in files_params:
                self._add(
                    "G002", "ERROR", "global",
                    "FILES keyword does not define PVTFILE",
                    location="FILES",
                    suggestion="Add PVTFILE=\"path/to/fluid.tab\" to the FILES keyword",
                )

        # G003: INTEGRATION must exist
        if "INTEGRATION" not in gk:
            self._add(
                "G003", "ERROR", "global",
                "INTEGRATION keyword is missing",
                location="(file level)",
                suggestion="Add an INTEGRATION keyword with at least ENDTIME",
            )

    # ------------------------------------------------------------------
    # T rules — Topology
    # ------------------------------------------------------------------

    def _run_topology_rules(self):
        flowpaths = self.parser.flowpaths
        nodes     = self.parser.nodes
        conns     = self.parser.connections

        # Build lookup sets
        fp_tags   = {fp["tag"] for fp in flowpaths if fp.get("tag")}
        node_tags = {nd["tag"] for nd in nodes if nd.get("tag")}

        # Collect all component/terminal references from CONNECTIONs
        # A connection looks like:
        #   {"TERMINALS": [{"component": "NODE_1", "terminal": "FLOWTERM_1"},
        #                  {"component": "FLOWPATH_1", "terminal": "INLET"}]}
        conn_fp_tags:   set[str] = set()   # flowpath tags seen in connections
        conn_node_tags: set[str] = set()   # node tags seen in connections

        # Per-flowpath terminal tracking for T002
        fp_inlet_seen:  set[str] = set()
        fp_outlet_seen: set[str] = set()

        for conn in conns:
            terminals = conn.get("TERMINALS", [])
            if not isinstance(terminals, list):
                continue
            for term in terminals:
                comp     = term.get("component", "")
                terminal = term.get("terminal", "").upper()

                if comp in fp_tags:
                    conn_fp_tags.add(comp)
                    if terminal == "INLET":
                        fp_inlet_seen.add(comp)
                    elif terminal == "OUTLET":
                        fp_outlet_seen.add(comp)
                elif comp in node_tags:
                    conn_node_tags.add(comp)
                else:
                    # T003 / T004: referenced component not found
                    if _looks_like_node(comp):
                        self._add(
                            "T003", "ERROR", "topology",
                            f"CONNECTION references node '{comp}' which is not defined",
                            location=f"CONNECTION ({comp})",
                            suggestion=f"Define NETWORKCOMPONENT TYPE=NODE, TAG={comp} or fix the tag name",
                        )
                    else:
                        self._add(
                            "T004", "ERROR", "topology",
                            f"CONNECTION references flowpath '{comp}' which is not defined",
                            location=f"CONNECTION ({comp})",
                            suggestion=f"Define NETWORKCOMPONENT TYPE=FLOWPATH, TAG={comp} or fix the tag name",
                        )

        # T001: every FLOWPATH must appear in at least one CONNECTION
        for fp in flowpaths:
            tag = fp.get("tag", "")
            if tag and tag not in conn_fp_tags:
                self._add(
                    "T001", "ERROR", "topology",
                    f"FLOWPATH '{tag}' is not connected to any node",
                    location=tag,
                    suggestion=f"Add CONNECTION statements linking {tag} to nodes",
                )

        # T002: every FLOWPATH needs both INLET and OUTLET connections
        for fp in flowpaths:
            tag = fp.get("tag", "")
            if not tag:
                continue
            missing = []
            if tag not in fp_inlet_seen:
                missing.append("INLET")
            if tag not in fp_outlet_seen:
                missing.append("OUTLET")
            if missing:
                self._add(
                    "T002", "ERROR", "topology",
                    f"FLOWPATH '{tag}' is missing {' and '.join(missing)} connection(s)",
                    location=tag,
                    suggestion=(
                        f"Add CONNECTION TERMINALS = (NODE_X FLOWTERM_1, {tag} "
                        f"{missing[0]}) for each missing terminal"
                    ),
                )

        # T005: orphan nodes (defined but not in any CONNECTION) — WARNING
        for nd in nodes:
            tag = nd.get("tag", "")
            if tag and tag not in conn_node_tags:
                self._add(
                    "T005", "WARNING", "topology",
                    f"NODE '{tag}' is defined but not referenced in any CONNECTION",
                    location=tag,
                    suggestion=f"Connect {tag} to a flowpath via a CONNECTION statement or remove it",
                )

        # T006: every FLOWPATH must contain at least one PIPE child
        for fp in flowpaths:
            tag      = fp.get("tag", "")
            children = fp.get("children", [])
            has_pipe = any(c["keyword"] == "PIPE" for c in children)
            if not has_pipe:
                self._add(
                    "T006", "ERROR", "topology",
                    f"FLOWPATH '{tag}' contains no PIPE definitions",
                    location=tag,
                    suggestion=f"Add at least one PIPE keyword inside NETWORKCOMPONENT TYPE=FLOWPATH, TAG={tag}",
                )

    # ------------------------------------------------------------------
    # B rules — Boundary conditions
    # ------------------------------------------------------------------

    def _run_boundary_rules(self):
        nodes = self.parser.nodes

        pressure_nodes = []
        for nd in nodes:
            params = {}
            for child in nd.get("children", []):
                if child["keyword"] == "PARAMETERS":
                    params = child["params"]
                    break
            nd_type = str(params.get("TYPE", "")).upper()
            if nd_type == "PRESSURE":
                pressure_nodes.append((nd, params))

        # B001: at least one PRESSURE node required
        if not pressure_nodes:
            self._add(
                "B001", "ERROR", "boundary",
                "No PRESSURE boundary condition found; at least one NODE must have TYPE=PRESSURE",
                location="(nodes section)",
                suggestion="Add TYPE=PRESSURE to one of the NODE definitions",
            )

        for nd, params in pressure_nodes:
            tag = nd.get("tag", "")
            loc = tag or _label(params, "(unknown node)")

            # B002: PRESSURE node must define PRESSURE value
            if "PRESSURE" not in params:
                self._add(
                    "B002", "ERROR", "boundary",
                    f"NODE '{loc}' has TYPE=PRESSURE but no PRESSURE value is defined",
                    location=loc,
                    suggestion="Add PRESSURE=<value> to the node PARAMETERS",
                )

            # B003: warn if PRESSURE node missing TEMPERATURE
            if "TEMPERATURE" not in params:
                self._add(
                    "B003", "WARNING", "boundary",
                    f"NODE '{loc}' has TYPE=PRESSURE but TEMPERATURE is not defined",
                    location=loc,
                    suggestion="Add TEMPERATURE=<value> to improve simulation accuracy",
                )

    # ------------------------------------------------------------------
    # M rules — Material & wall integrity
    # ------------------------------------------------------------------

    def _run_material_rules(self):
        materials = self.parser.materials
        walls     = self.parser.walls
        flowpaths = self.parser.flowpaths

        # Build label lookup sets
        material_labels: set[str] = set()
        for mat in materials:
            lbl = mat.get("LABEL")
            if lbl:
                material_labels.add(str(lbl))

        wall_labels: set[str] = set()
        for wall in walls:
            lbl = wall.get("LABEL")
            if lbl:
                wall_labels.add(str(lbl))

        # M001: every material name in WALL MATERIAL tuple must match a MATERIAL LABEL
        for wall in walls:
            wall_lbl = str(wall.get("LABEL", "(unnamed)"))
            mat_val  = wall.get("MATERIAL")
            mat_list = _as_list(mat_val)
            for mat_name in mat_list:
                mat_name_str = str(mat_name)
                if mat_name_str and mat_name_str not in material_labels:
                    self._add(
                        "M001", "ERROR", "material",
                        f"WALL '{wall_lbl}' references undefined material '{mat_name_str}'",
                        location=f"WALL {wall_lbl}",
                        suggestion=f"Define MATERIAL LABEL=\"{mat_name_str}\" or correct the material name",
                    )

        # Collect walls used by PIPEs and check M002
        used_walls: set[str] = set()
        for fp in flowpaths:
            fp_tag = fp.get("tag", "")
            for child in fp.get("children", []):
                if child["keyword"] != "PIPE":
                    continue
                params   = child["params"]
                pipe_lbl = str(params.get("LABEL", "(unnamed)"))
                loc      = f"{fp_tag} / PIPE {pipe_lbl}"
                wall_ref = params.get("WALL")
                if wall_ref is not None:
                    wall_ref_str = str(wall_ref)
                    used_walls.add(wall_ref_str)
                    if wall_ref_str not in wall_labels:
                        self._add(
                            "M002", "ERROR", "material",
                            f"PIPE '{pipe_lbl}' in '{fp_tag}' references undefined WALL '{wall_ref_str}'",
                            location=loc,
                            suggestion=f"Define WALL LABEL=\"{wall_ref_str}\" or correct the wall name",
                        )

        # M003: unused materials — WARNING
        used_mat_names: set[str] = set()
        for wall in walls:
            for mat_name in _as_list(wall.get("MATERIAL")):
                used_mat_names.add(str(mat_name))

        for mat in materials:
            lbl = str(mat.get("LABEL", ""))
            if lbl and lbl not in used_mat_names:
                self._add(
                    "M003", "WARNING", "material",
                    f"MATERIAL '{lbl}' is defined but not referenced by any WALL",
                    location=f"MATERIAL {lbl}",
                    suggestion=f"Remove MATERIAL '{lbl}' or add it to a WALL MATERIAL list",
                )

        # M004: unused walls — WARNING
        for wall in walls:
            lbl = str(wall.get("LABEL", ""))
            if lbl and lbl not in used_walls:
                self._add(
                    "M004", "WARNING", "material",
                    f"WALL '{lbl}' is defined but not referenced by any PIPE",
                    location=f"WALL {lbl}",
                    suggestion=f"Remove WALL '{lbl}' or reference it in a PIPE WALL parameter",
                )

        # M005: WALL THICKNESS and MATERIAL tuple lengths must match
        for wall in walls:
            wall_lbl  = str(wall.get("LABEL", "(unnamed)"))
            thickness = _as_list(wall.get("THICKNESS"))
            material  = _as_list(wall.get("MATERIAL"))
            if thickness and material and len(thickness) != len(material):
                self._add(
                    "M005", "ERROR", "material",
                    (
                        f"WALL '{wall_lbl}' THICKNESS has {len(thickness)} entries "
                        f"but MATERIAL has {len(material)} entries"
                    ),
                    location=f"WALL {wall_lbl}",
                    suggestion="Ensure THICKNESS and MATERIAL tuples have the same number of elements",
                )

    # ------------------------------------------------------------------
    # P rules — Physical plausibility
    # ------------------------------------------------------------------

    def _run_physical_rules(self):
        flowpaths = self.parser.flowpaths
        walls     = self.parser.walls

        for fp in flowpaths:
            fp_tag = fp.get("tag", "")
            sections: list[tuple[str, float]] = []
            for child in fp.get("children", []):
                if child["keyword"] != "PIPE":
                    continue
                params   = child["params"]
                pipe_lbl = str(params.get("LABEL", "(unnamed)"))
                loc      = f"{fp_tag} / PIPE {pipe_lbl}"
                for seg_val in _as_list(params.get("LSEGMENT")):
                    seg_num = float(seg_val) if isinstance(seg_val, (int, float)) else _numeric(seg_val)
                    if seg_num is not None and seg_num > 0:
                        sections.append((pipe_lbl, seg_num))

                # P001: DIAMETER > 0
                diam_val = params.get("DIAMETER")
                diam     = _numeric(diam_val)
                diam_ft  = _to_ft(diam, diam_val)
                if diam is not None:
                    if diam <= 0:
                        self._add(
                            "P001", "ERROR", "physical",
                            f"PIPE '{pipe_lbl}' in '{fp_tag}' has non-positive DIAMETER ({diam})",
                            location=loc,
                            suggestion="Set DIAMETER to a positive value",
                        )
                    else:
                        # P004: warn if DIAMETER > 10 ft
                        if diam_ft is not None and diam_ft > 10.0:
                            self._add(
                                "P004", "WARNING", "physical",
                                f"PIPE '{pipe_lbl}' in '{fp_tag}' has unusually large DIAMETER "
                                f"({diam} {_unit(diam_val)}; ~{diam_ft:.2f} ft)",
                                location=loc,
                                suggestion="Verify the diameter value and units",
                            )
                        # P005: warn if DIAMETER < 0.01 ft
                        if diam_ft is not None and 0 < diam_ft < 0.01:
                            self._add(
                                "P005", "WARNING", "physical",
                                f"PIPE '{pipe_lbl}' in '{fp_tag}' has unusually small DIAMETER "
                                f"({diam} {_unit(diam_val)}; ~{diam_ft:.4f} ft)",
                                location=loc,
                                suggestion="Verify the diameter value and units",
                            )

                # P002: all LSEGMENT values > 0
                lseg_raw = params.get("LSEGMENT")
                lseg     = _as_list(lseg_raw)
                for seg_val in lseg:
                    seg_num = _numeric(seg_val) if not isinstance(seg_val, (int, float)) else float(seg_val)
                    if isinstance(seg_val, (int, float)):
                        seg_num = float(seg_val)
                    else:
                        seg_num = _numeric(seg_val)
                    if seg_num is not None and seg_num <= 0:
                        self._add(
                            "P002", "ERROR", "physical",
                            f"PIPE '{pipe_lbl}' in '{fp_tag}' has non-positive LSEGMENT value ({seg_num})",
                            location=loc,
                            suggestion="All LSEGMENT values must be greater than zero",
                        )
                        break  # one finding per pipe is enough

                # P003: ROUGHNESS >= 0
                rough = _numeric(params.get("ROUGHNESS"))
                if rough is not None and rough < 0:
                    self._add(
                        "P003", "ERROR", "physical",
                        f"PIPE '{pipe_lbl}' in '{fp_tag}' has negative ROUGHNESS ({rough})",
                        location=loc,
                        suggestion="Set ROUGHNESS to a non-negative value",
                    )

                # P006: NSEGMENT must match len(LSEGMENT)
                nseg_raw = params.get("NSEGMENT")
                nseg     = _numeric(nseg_raw)
                if nseg is not None and lseg:
                    if int(nseg) != len(lseg):
                        self._add(
                            "P006", "ERROR", "physical",
                            (
                                f"PIPE '{pipe_lbl}' in '{fp_tag}' NSEGMENT={int(nseg)} "
                                f"but LSEGMENT has {len(lseg)} elements"
                            ),
                            location=loc,
                            suggestion="Ensure NSEGMENT equals the number of values in LSEGMENT",
                        )

            # P008: neighbouring section lengths inside a flowpath, across pipe
            # boundaries too, should stay within a 0.5-2 ratio (OLGA good practice).
            for (left_pipe, left), (right_pipe, right) in zip(sections, sections[1:]):
                ratio = max(left, right) / min(left, right)
                if ratio > 2.0 + 1e-9:
                    self._add(
                        "P008", "WARNING", "physical",
                        (
                            f"Neighbouring sections in '{fp_tag}' differ by {ratio:.2f}x "
                            f"({left_pipe} {left:g} -> {right_pipe} {right:g})"
                        ),
                        location=f"{fp_tag} / PIPE {right_pipe}",
                        suggestion="Grade the section lengths so neighbours stay within a 0.5-2 ratio",
                    )
                    break

        # P007: WALL THICKNESS values > 0
        for wall in walls:
            wall_lbl  = str(wall.get("LABEL", "(unnamed)"))
            thickness = _as_list(wall.get("THICKNESS"))
            for t_val in thickness:
                t_num = float(t_val) if isinstance(t_val, (int, float)) else _numeric(t_val)
                if t_num is not None and t_num <= 0:
                    self._add(
                        "P007", "ERROR", "physical",
                        f"WALL '{wall_lbl}' has non-positive THICKNESS value ({t_num})",
                        location=f"WALL {wall_lbl}",
                        suggestion="All WALL THICKNESS values must be greater than zero",
                    )
                    break

    # ------------------------------------------------------------------
    # S rules — Time-stepping
    # ------------------------------------------------------------------

    def _run_timestep_rules(self):
        gk = self.parser.global_keywords
        if "INTEGRATION" not in gk:
            return  # G003 already fires

        integ = gk["INTEGRATION"]

        endtime   = _numeric(integ.get("ENDTIME"))
        starttime = _numeric(integ.get("STARTTIME", 0))
        dtstart   = _numeric(integ.get("DTSTART"))
        maxdt     = _numeric(integ.get("MAXDT"))
        mindt     = _numeric(integ.get("MINDT"))

        # S001: ENDTIME must be defined
        if "ENDTIME" not in integ:
            self._add(
                "S001", "ERROR", "timestep",
                "INTEGRATION does not define ENDTIME",
                location="INTEGRATION",
                suggestion="Add ENDTIME=<value> to the INTEGRATION keyword",
            )

        # S002: ENDTIME > STARTTIME
        if endtime is not None and starttime is not None:
            if endtime <= starttime:
                self._add(
                    "S002", "ERROR", "timestep",
                    f"INTEGRATION ENDTIME ({endtime}) must be greater than STARTTIME ({starttime})",
                    location="INTEGRATION",
                    suggestion="Set ENDTIME to a value greater than STARTTIME",
                )

        # S003: DTSTART > 0
        if "DTSTART" in integ and dtstart is not None and dtstart <= 0:
            self._add(
                "S003", "ERROR", "timestep",
                f"INTEGRATION DTSTART ({dtstart}) must be positive",
                location="INTEGRATION",
                suggestion="Set DTSTART to a positive value",
            )

        # S004: MAXDT > 0
        if "MAXDT" in integ and maxdt is not None and maxdt <= 0:
            self._add(
                "S004", "ERROR", "timestep",
                f"INTEGRATION MAXDT ({maxdt}) must be positive",
                location="INTEGRATION",
                suggestion="Set MAXDT to a positive value",
            )

        # S005: MINDT > 0
        if "MINDT" in integ and mindt is not None and mindt <= 0:
            self._add(
                "S005", "ERROR", "timestep",
                f"INTEGRATION MINDT ({mindt}) must be positive",
                location="INTEGRATION",
                suggestion="Set MINDT to a positive value",
            )

        # S006: MINDT <= MAXDT
        if mindt is not None and maxdt is not None:
            if mindt > maxdt:
                self._add(
                    "S006", "ERROR", "timestep",
                    f"INTEGRATION MINDT ({mindt}) is greater than MAXDT ({maxdt})",
                    location="INTEGRATION",
                    suggestion="Ensure MINDT <= MAXDT",
                )

        # S007: warn if DTSTART > MAXDT
        if dtstart is not None and maxdt is not None:
            if dtstart > maxdt:
                self._add(
                    "S007", "WARNING", "timestep",
                    f"INTEGRATION DTSTART ({dtstart}) is greater than MAXDT ({maxdt}); "
                    "OLGA will clamp the initial timestep",
                    location="INTEGRATION",
                    suggestion="Set DTSTART <= MAXDT to avoid unexpected clamping",
                )

        # S008: warn if DTSTART < MINDT
        if dtstart is not None and mindt is not None:
            if dtstart < mindt:
                self._add(
                    "S008", "WARNING", "timestep",
                    f"INTEGRATION DTSTART ({dtstart}) is less than MINDT ({mindt})",
                    location="INTEGRATION",
                    suggestion="Set DTSTART >= MINDT",
                )


# ---------------------------------------------------------------------------
# Unit-conversion helpers (for P004/P005 diameter checks)
# ---------------------------------------------------------------------------

# Approximate conversion factors to feet for common length units
_TO_FT: dict[str, float] = {
    "ft":  1.0,
    "in":  1.0 / 12.0,
    "m":   3.28084,
    "cm":  0.0328084,
    "mm":  0.00328084,
}


def _unit(val) -> str:
    """Return the unit string from a parsed value, or empty string."""
    if isinstance(val, dict):
        return str(val.get("unit", ""))
    return ""


def _to_ft(numeric_val: float | None, raw_val) -> float | None:
    """Convert a numeric pipe diameter to feet for threshold checks.

    If no unit is present, assumes the value is already in feet (OLGA field default).
    Returns None if conversion is not possible.
    """
    if numeric_val is None:
        return None
    unit = _unit(raw_val).lower()
    factor = _TO_FT.get(unit, 1.0)  # default: assume feet
    return numeric_val * factor


def _looks_like_node(tag: str) -> bool:
    """Heuristic: does this tag look like a NODE rather than a FLOWPATH?"""
    upper = tag.upper()
    return "NODE" in upper


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python genkey_validator.py <file.genkey>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    if not Path(filepath).exists():
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    parser    = GenkeyParser(filepath)
    validator = GenkeyValidator(parser)
    validator.validate()

    print(validator.summary())

    errors = [f for f in validator._findings if f["severity"] == "ERROR"]
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
