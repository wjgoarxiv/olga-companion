"""
genkey_builder.py -- Build OLGA .genkey simulation files from parameters.

Constructs valid .genkey files from scratch without requiring the OLGA GUI.
Supports 6 topology templates with sensible defaults.

Usage (CLI):
    python genkey_builder.py simple_pipeline --save output.genkey
    python genkey_builder.py production_well --endtime 86400 --save well.genkey
    python genkey_builder.py --list-topologies
    python genkey_builder.py simple_pipeline --json

Exit codes:
    0 -- success
    1 -- validation errors in generated file
    2 -- usage / argument error
"""

import argparse
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Import validator for post-build check
# ---------------------------------------------------------------------------

try:
    from genkey_parser import GenkeyParser
    from genkey_validator import GenkeyValidator
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from genkey_parser import GenkeyParser
    from genkey_validator import GenkeyValidator


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_tuple(values, unit=None):
    """Format a list as an OLGA tuple string: (v1, v2, v3) unit"""
    inner = ", ".join(_fmt_scalar(v) for v in values)
    s = f"({inner})"
    if unit:
        s += f" {unit}"
    return s


def _fmt_str_tuple(values):
    """Format a list of strings as an OLGA quoted-string tuple."""
    inner = ", ".join(f'"{v}"' for v in values)
    return f"({inner})"


def _fmt_scalar(v):
    """Format a single numeric or string value."""
    if isinstance(v, float):
        # Use scientific notation for very small numbers
        if v != 0 and abs(v) < 1e-3:
            return f"{v:g}"
        return f"{v:g}"
    if isinstance(v, int):
        return str(v)
    return str(v)


def _fmt_num_unit(value, unit):
    """Format number with unit: 3600 s"""
    return f"{_fmt_scalar(value)} {unit}"


# ---------------------------------------------------------------------------
# GenkeyBuilder
# ---------------------------------------------------------------------------

TOPOLOGIES = [
    'simple_pipeline',
    'production_well',
    'well_pipeline',
    'subsea_tieback',
    'riser',
    'separator',
]


class GenkeyBuilder:
    """Build OLGA .genkey simulation files from parameters.

    Parameters
    ----------
    topology : str
        One of: 'simple_pipeline', 'production_well', 'well_pipeline',
        'subsea_tieback', 'riser', 'separator'
    """

    def __init__(self, topology='simple_pipeline'):
        if topology not in TOPOLOGIES:
            raise ValueError(
                f"Unknown topology '{topology}'. "
                f"Choose from: {', '.join(TOPOLOGIES)}"
            )
        self.topology = topology

        # Simulation parameters
        self._endtime = 3600.0
        self._dtstart = 0.1
        self._mindt = 0.001
        self._maxdt = 1.0
        self._starttime = 0.0
        self._steadystate = True

        # Fluid
        self._pvtfile = "./fluid.tab"
        # Fluid tag used on BRANCH/NODE. OLGA resolves this against the PVT
        # table label (a bare number like 1 is NOT accepted by the solver).
        # None => resolved from the referenced .tab at build time.
        self._fluid_label = None
        self._output_dir = None

        # Ambient heat-transfer defaults (HEATTRANSFER is a required keyword).
        self._ambient_temp = 20.0   # C
        self._ambient_h = 10.0      # W/m2-K

        # Materials: list of dicts
        self._materials = []

        # Walls: list of dicts
        self._walls = []

        # Flowpaths: tag -> {label, pipes: [...], branch_fluid: int}
        self._flowpaths = {}

        # Nodes: tag -> {label, node_type, pressure, temperature, gasfraction, ...}
        self._nodes = {}

        # Valves: list of {flowpath, pipe_label, position, valve_type, label, opening}
        self._valves = []

        # Connections: list of (comp1, terminal1, comp2, terminal2)
        self._connections = []

        # Output config
        self._trend_vars = ['PT', 'TM', 'HOL', 'GT']
        self._profile_vars = ['PT', 'TM', 'HOL']
        self._trend_dt = 10.0
        self._profile_dt = 60.0

        # Reservoir contacts: list of dicts
        self._reservoir_contacts = []

        # Linear IPR: list of dicts
        self._linear_iprs = []

        # Compositional tracking
        self._compositional = False
        self._flash_formulation = 'PH'
        self._feed_file = None
        self._compoptions = {}

        # OPC server
        self._server_options = None
        self._server_data = None

        # Apply template defaults
        template_fn = getattr(self, f'_template_{topology}', None)
        if template_fn:
            template_fn()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_simulation(self, endtime, dtstart=0.1, mindt=0.001, maxdt=1.0,
                       steadystate=False, starttime=0):
        """Set simulation time parameters."""
        self._endtime = float(endtime)
        self._dtstart = float(dtstart)
        self._mindt = float(mindt)
        self._maxdt = float(maxdt)
        self._steadystate = bool(steadystate)
        self._starttime = float(starttime)
        return self

    def set_fluid(self, pvtfile):
        """Set PVT fluid file path."""
        self._pvtfile = str(pvtfile)
        return self

    def set_fluid_label(self, label):
        """Override the fluid tag used on BRANCH/NODE FLUID keys.

        When unset, the label is parsed from the referenced ``.tab`` at build
        time (OLGA rejects a bare numeric FLUID tag).
        """
        self._fluid_label = str(label) if label else None
        return self

    def add_material(self, label, conductivity=50.0, capacity=500.0,
                     density=7850.0, mat_type='SOLID'):
        """Add a material definition (defaults: carbon steel)."""
        self._materials.append({
            'label': label,
            'conductivity': conductivity,
            'capacity': capacity,
            'density': density,
            'type': mat_type,
        })
        return self

    def add_wall(self, label, thicknesses, materials):
        """Add a wall definition.

        Parameters
        ----------
        thicknesses : list of float
            Layer thicknesses in metres.
        materials : list of str
            Material labels, same length as thicknesses.
        """
        if len(thicknesses) != len(materials):
            raise ValueError(
                f"Wall '{label}': thicknesses ({len(thicknesses)}) and "
                f"materials ({len(materials)}) must have same length"
            )
        self._walls.append({
            'label': label,
            'thicknesses': list(thicknesses),
            'materials': list(materials),
        })
        return self

    def add_pipe(self, flowpath, label, diameter, lsegment, elevation,
                 wall=None, roughness=5e-5, nsegment=None):
        """Add a pipe to a flowpath.

        Parameters
        ----------
        flowpath : str
            Flowpath tag (e.g., 'FP_1').
        label : str
            Pipe label.
        diameter : float
            Pipe inner diameter in metres.
        lsegment : list of float
            Section lengths in metres.
        elevation : list of float
            Elevation changes per section in metres.
        wall : str or None
            Wall label reference.
        roughness : float
            Pipe roughness in metres.
        nsegment : int or None
            Number of segments (default: len(lsegment)).
        """
        if flowpath not in self._flowpaths:
            self._flowpaths[flowpath] = {
                'label': flowpath,
                'pipes': [],
                'branch_fluid': 1,
            }
        if nsegment is None:
            nsegment = len(lsegment)
        self._flowpaths[flowpath]['pipes'].append({
            'label': label,
            'diameter': float(diameter),
            'lsegment': [float(x) for x in lsegment],
            'elevation': [float(x) for x in elevation],
            'wall': wall,
            'roughness': float(roughness),
            'nsegment': int(nsegment),
        })
        return self

    def add_node(self, label, node_type='PRESSURE', pressure=None,
                 temperature=None, gasfraction=None):
        """Add a boundary node.

        Parameters
        ----------
        label : str
            Node tag (used as TAG in NETWORKCOMPONENT).
        node_type : str
            'PRESSURE' or 'CLOSED'.
        pressure : float or None
            Boundary pressure in Pa.
        temperature : float or None
            Temperature in degrees C.
        gasfraction : float or None
            Gas fraction 0-1.
        """
        self._nodes[label] = {
            'label': label,
            'node_type': node_type.upper(),
            'pressure': pressure,
            'temperature': temperature,
            'gasfraction': gasfraction,
        }
        return self

    def add_valve(self, flowpath, pipe_label, position=0.5,
                  valve_type='HYDROVALVE', label=None, opening=1.0):
        """Add a valve to a flowpath at a position along a pipe."""
        if label is None:
            label = f"VALVE_{len(self._valves) + 1}"
        self._valves.append({
            'flowpath': flowpath,
            'pipe_label': pipe_label,
            'position': float(position),
            'valve_type': valve_type,
            'label': label,
            'opening': float(opening),
        })
        return self

    def add_connection(self, comp1, terminal1, comp2, terminal2):
        """Add a connection between two components.

        Example: add_connection('INLET', 'FLOWTERM_1', 'FP_1', 'INLET')
        """
        self._connections.append((comp1, terminal1, comp2, terminal2))
        return self

    def set_output(self, trend_vars=None, profile_vars=None,
                   trend_dt=10, profile_dt=60):
        """Set output configuration.

        Parameters
        ----------
        trend_vars : list of str or None
            OLGA variable names for TRENDDATA (default: PT, TM, HOL, GT).
        profile_vars : list of str or None
            Variables for PROFILEDATA (default: PT, TM, HOL).
        trend_dt : float
            Trend output interval in seconds.
        profile_dt : float
            Profile output interval in seconds.
        """
        if trend_vars is not None:
            self._trend_vars = list(trend_vars)
        if profile_vars is not None:
            self._profile_vars = list(profile_vars)
        self._trend_dt = float(trend_dt)
        self._profile_dt = float(profile_dt)
        return self

    def set_compositional(self, on=True, formulation='PH'):
        """Enable/disable compositional tracking and set flash formulation.

        Parameters
        ----------
        on : bool
            True sets COMPOSITIONAL=ON, False sets COMPOSITIONAL=OFF.
        formulation : str
            FLASHFORMULATION value: 'PH' (default) or 'PT'.
        """
        self._compositional = bool(on)
        self._flash_formulation = str(formulation).upper()
        return self

    def set_feed_file(self, mfl_path):
        """Set FEEDFILE reference for compositional tracking.

        Parameters
        ----------
        mfl_path : str
            Path to the MULTIFLASH feed definition (.mfl) file.
        """
        self._feed_file = str(mfl_path)
        return self

    def set_compoptions(self, **kwargs):
        """Set COMPOPTIONS keyword parameters.

        Common keys: FLASHTYPE, NPHASE, WATER.
        Example: set_compoptions(FLASHTYPE='DEFAULT', NPHASE=2)
        """
        self._compoptions.update(kwargs)
        return self

    def add_reservoir_contact(self, label, flowpath, pipe_label,
                              position=0.5, isothermal=True):
        """Add a RESERVOIRCONTACT keyword.

        Parameters
        ----------
        label : str
            Reservoir contact label.
        flowpath : str
            Flowpath tag where the contact is placed.
        pipe_label : str
            Pipe label within the flowpath.
        position : float
            Fractional position along the pipe (0-1).
        isothermal : bool
            If True, ISOTHERMAL=YES.
        """
        self._reservoir_contacts.append({
            'label': label,
            'flowpath': flowpath,
            'pipe_label': pipe_label,
            'position': float(position),
            'isothermal': bool(isothermal),
        })
        return self

    def add_linear_ipr(self, label, time=0, model_option='MASS',
                       a=0, b=2.1e-6):
        """Add a LINEAR IPR keyword.

        Parameters
        ----------
        label : str
            IPR label.
        time : float
            Time in seconds.
        model_option : str
            MODELOPTION value (e.g., 'MASS').
        a : float
            A coefficient in kg/s.
        b : float
            B coefficient in kg/s-Pa.
        """
        self._linear_iprs.append({
            'label': label,
            'time': float(time),
            'model_option': str(model_option).upper(),
            'a': float(a),
            'b': float(b),
        })
        return self

    def build(self):
        """Return the complete .genkey text string."""
        sections = []

        # 1. Header comments
        sections.append(self._build_header())

        # 2. OPTIONS / CASE
        sections.append(self._build_options())

        # 3. FILES
        sections.append(self._build_files())

        # 3b. COMPOPTIONS (compositional tracking)
        sections.append(self._build_compoptions())

        # 3c. SERVEROPTIONS
        if self._server_options:
            sections.append(self._build_server_options())

        # 3d. SERVERDATA
        if self._server_data:
            sections.append(self._build_server_data())

        # 4. INTEGRATION
        sections.append(self._build_integration())

        # 5. OUTPUT / TREND / PROFILE
        sections.append(self._build_output())

        # 6. MATERIAL definitions
        sections.append(self._build_materials())

        # 7. WALL definitions
        sections.append(self._build_walls())

        # 8. NETWORKCOMPONENT blocks - flowpaths
        sections.append(self._build_flowpaths())

        # 9. NETWORKCOMPONENT blocks - nodes
        sections.append(self._build_nodes())

        # 10. CONNECTION statements
        sections.append(self._build_connections())

        # 11. RESERVOIRCONTACT
        sections.append(self._build_reservoir_contacts())

        # 12. LINEAR IPR
        sections.append(self._build_linear_iprs())

        # 13. ENDCASE
        sections.append("ENDCASE\n")

        return "\n".join(s for s in sections if s)

    def save(self, filepath):
        """Write .genkey to disk."""
        # Remember the output directory so a relative PVT reference can be
        # resolved to read its fluid label.
        self._output_dir = Path(filepath).parent
        self._resolved_fluid = "unset"
        text = self.build()
        Path(filepath).write_text(text, encoding='utf-8')
        return filepath

    def validate(self):
        """Validate the built genkey by writing to a temp file and running
        the validator. Returns (errors, warnings, findings)."""
        text = self.build()
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.genkey', delete=False, encoding='utf-8'
        ) as f:
            f.write(text)
            tmp_path = f.name
        try:
            parser = GenkeyParser(tmp_path)
            validator = GenkeyValidator(parser)
            findings = validator.validate()
            errors = [f for f in findings if f['severity'] == 'ERROR']
            warnings = [f for f in findings if f['severity'] == 'WARNING']
            return errors, warnings, findings
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Build sections
    # ------------------------------------------------------------------

    def _build_header(self):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return (
            "!**************************************************************************************\n"
            f"! Generated by genkey_builder.py on {ts}\n"
            f"! Topology: {self.topology}\n"
            "!**************************************************************************************"
        )

    def _build_options(self):
        ss = "ON" if self._steadystate else "OFF"
        comp = "ON" if self._compositional else "OFF"
        options_line = f"OPTIONS STEADYSTATE={ss}, COMPOSITIONAL={comp}, FLOWMODEL=OLGAHD"
        if self._compositional:
            options_line += f", FLASHFORMULATION={self._flash_formulation}"
        lines = [
            options_line,
            f'CASE AUTHOR=genkey_builder, PROJECT=OLGA, TITLE="{self.topology}"',
        ]
        return "\n".join(lines)

    def _build_files(self):
        line = f'FILES PVTFILE="{self._pvtfile}"'
        if self._feed_file is not None:
            line += f', FEEDFILE="{self._feed_file}"'
        return line

    def _build_compoptions(self):
        if not self._compoptions:
            return ""
        parts = ", ".join(
            f"{k}={_fmt_scalar(v)}" for k, v in self._compoptions.items()
        )
        return f"COMPOPTIONS {parts}"

    def _build_integration(self):
        parts = [
            "INTEGRATION",
            f"ENDTIME={_fmt_num_unit(self._endtime, 's')},",
            f"DTSTART={_fmt_num_unit(self._dtstart, 's')},",
            f"MINDT={_fmt_num_unit(self._mindt, 's')},",
            f"MAXDT={_fmt_num_unit(self._maxdt, 's')},",
            f"STARTTIME={_fmt_num_unit(self._starttime, 's')}",
        ]
        return " ".join(parts)

    def _build_output(self):
        lines = [
            f"OUTPUT DTOUT={_fmt_num_unit(self._profile_dt, 's')}",
            f"TREND DTPLOT={_fmt_num_unit(self._trend_dt, 's')}",
            f"PROFILE DTPLOT={_fmt_num_unit(self._profile_dt, 's')}",
        ]
        return "\n".join(lines)

    def _build_materials(self):
        if not self._materials:
            return ""
        lines = []
        for mat in self._materials:
            lines.append(
                f'MATERIAL LABEL="{mat["label"]}", '
                f'TYPE={mat["type"]}, '
                f'CONDUCTIVITY={_fmt_scalar(mat["conductivity"])} W/m-K, '
                f'CAPACITY={_fmt_scalar(mat["capacity"])} J/kg-K, '
                f'DENSITY={_fmt_scalar(mat["density"])} kg/m3'
            )
        return "\n".join(lines)

    def _build_walls(self):
        if not self._walls:
            return ""
        lines = []
        for wall in self._walls:
            n_layers = len(wall['thicknesses'])
            if n_layers == 1:
                # Single-layer walls use scalar THICKNESS/MATERIAL. OLGA
                # (2022.1.0 and 2025) rejects the single-element tuple form
                # `THICKNESS=(x) m, MATERIAL=("m")` at verification. No LAYERS
                # key: OLGA derives the layer count from the tuple length.
                thick_str = _fmt_num_unit(wall['thicknesses'][0], 'm')
                mat_str = f'"{wall["materials"][0]}"'
                lines.append(
                    f'WALL LABEL="{wall["label"]}", '
                    f'THICKNESS={thick_str}, '
                    f'MATERIAL={mat_str}'
                )
            else:
                thick_str = _fmt_tuple(wall['thicknesses'], 'm')
                mat_str = _fmt_str_tuple(wall['materials'])
                lines.append(
                    f'WALL LABEL="{wall["label"]}", '
                    f'THICKNESS={thick_str}, '
                    f'MATERIAL={mat_str}'
                )
        return "\n".join(lines)

    def _resolve_fluid_label(self):
        """Return the fluid tag for BRANCH/NODE FLUID keys.

        OLGA resolves FLUID against a PVT table LABEL; a bare number is
        rejected. Precedence: explicit ``set_fluid_label`` -> the LABEL parsed
        from the referenced ``.tab`` -> ``None`` (caller falls back to the
        numeric tag and the validator flags it).
        """
        if getattr(self, "_resolved_fluid", "unset") != "unset":
            return self._resolved_fluid
        label = self._fluid_label
        if not label:
            candidates = [Path(self._pvtfile)]
            if self._output_dir:
                candidates.append(Path(self._output_dir) / self._pvtfile)
            for cand in candidates:
                try:
                    if cand.exists():
                        text = cand.read_text(encoding="utf-8", errors="replace")
                        m = re.search(
                            r'PVTTABLE\s+LABEL\s*=\s*"?([^",\s]+)"?', text, re.I
                        )
                        if m:
                            label = m.group(1)
                            break
                except OSError:
                    pass
        self._resolved_fluid = label
        return label

    def _fluid_ref(self):
        label = self._resolve_fluid_label()
        return f'"{label}"' if label else "1"

    def _boundary_state_for(self, tag):
        """Pressure/temperature/gas fraction of a PRESSURE node on this flowpath.

        Used only to seed INITIALCONDITIONS, so the initial state reuses values
        the case already declares instead of introducing new ones.
        """
        for comp1, _t1, comp2, _t2 in self._connections:
            for node_tag, fp_tag in ((comp1, comp2), (comp2, comp1)):
                if fp_tag != tag:
                    continue
                node = self._nodes.get(node_tag)
                if not node or node.get("node_type") != "PRESSURE":
                    continue
                if node.get("pressure") is None or node.get("temperature") is None:
                    continue
                return node
        return None

    def _build_flowpaths(self):
        if not self._flowpaths:
            return ""
        blocks = []
        for tag, fp in self._flowpaths.items():
            fp_lines = []
            fp_lines.append(f"NETWORKCOMPONENT TYPE=FLOWPATH, TAG={tag}")
            fp_lines.append(f' PARAMETERS LABEL="{fp["label"]}"')
            fp_lines.append(f' BRANCH FLUID={self._fluid_ref()}')

            # Without the steady-state preprocessor OLGA requires an explicit
            # initial state ("Initial conditions have to be specified either
            # using INITIALCONDITIONS, RESTART or steady state preprocessor").
            if not self._steadystate:
                node = self._boundary_state_for(tag)
                if node is not None:
                    parts = [
                        f'PRESSURE={_fmt_num_unit(node["pressure"], "Pa")}',
                        f'TEMPERATURE={_fmt_num_unit(node["temperature"], "C")}',
                    ]
                    # INITIALCONDITIONS takes VOIDFRACTION (gas volume
                    # fraction); GASFRACTION is a NODE-only key and OLGA
                    # rejects it here.
                    if node.get("gasfraction") is not None:
                        parts.append(
                            f'VOIDFRACTION={_fmt_scalar(node["gasfraction"])} -'
                        )
                    fp_lines.append(f' INITIALCONDITIONS {", ".join(parts)}')

            # Geometry: start at origin, compute cumulative positions. Y is the
            # vertical axis in OLGA geometry; X carries the plan distance as the
            # horizontal projection and Z stays 0.
            x_pos = 0.0
            y_pos = 0.0
            fp_lines.append(
                f' GEOMETRY LABEL="G-{fp["label"]}", '
                f'XSTART=0 m, YSTART=0 m, ZSTART=0 m'
            )

            # Output data inside flowpath
            if self._trend_vars:
                var_str = _fmt_str_tuple(self._trend_vars) if any(
                    ' ' in v for v in self._trend_vars
                ) else f"({', '.join(self._trend_vars)})"
                fp_lines.append(f' OUTPUTDATA VARIABLE={var_str}')

            # Pipes
            for pipe in fp['pipes']:
                total_length = sum(pipe['lsegment'])
                total_elev = sum(pipe['elevation'])
                x_end = x_pos + max(total_length * total_length - total_elev * total_elev, 0.0) ** 0.5
                y_end = y_pos + total_elev

                lseg_str = _fmt_tuple(pipe['lsegment'], 'm')

                parts = [
                    f' PIPE LABEL={pipe["label"]},',
                    f'DIAMETER={_fmt_num_unit(pipe["diameter"], "m")},',
                    f'ROUGHNESS={_fmt_num_unit(pipe["roughness"], "m")},',
                    # OLGA requires an explicit pipe LENGTH; it must equal the
                    # LSEGMENT sum. ELEVATION is the scalar total rise over the
                    # pipe (a per-segment tuple is rejected as "non list").
                    f'LENGTH={_fmt_num_unit(total_length, "m")},',
                    f'NSEGMENT={pipe["nsegment"]},',
                    f'LSEGMENT={lseg_str},',
                    f'ELEVATION={_fmt_num_unit(total_elev, "m")},',
                    f'XEND={_fmt_num_unit(x_end, "m")},',
                    f'YEND={_fmt_num_unit(y_end, "m")},',
                    f'ZEND=0 m',
                ]
                if pipe['wall']:
                    parts.insert(1, f'WALL="{pipe["wall"]}",')

                fp_lines.append(" ".join(parts))

                x_pos = x_end
                y_pos = y_end

            # HEATTRANSFER is a required FLOWPATH keyword. Emit one entry
            # covering every pipe with a mild HGIVEN ambient default.
            pipe_labels = [p['label'] for p in fp['pipes']]
            if pipe_labels:
                if len(pipe_labels) == 1:
                    pipe_ref = f'"{pipe_labels[0]}"'
                else:
                    pipe_ref = _fmt_str_tuple(pipe_labels)
                fp_lines.append(
                    f' HEATTRANSFER LABEL="HT_{tag}", PIPE={pipe_ref}, '
                    f'HOUTEROPTION=HGIVEN, '
                    f'TAMBIENT={_fmt_num_unit(self._ambient_temp, "C")}, '
                    f'HAMBIENT={_fmt_num_unit(self._ambient_h, "W/m2-K")}'
                )

            # POSITION near the outlet so TRENDDATA has an anchor and the TPL
            # carries trend variables (otherwise CATALOG is empty).
            if fp['pipes']:
                last_pipe = fp['pipes'][-1]
                pos_label = f"POS_{tag}"
                fp_lines.append(
                    f' POSITION LABEL="{pos_label}", '
                    f'PIPE={last_pipe["label"]}, SECTION={last_pipe["nsegment"]}'
                )

            # Valves inside this flowpath
            for valve in self._valves:
                if valve['flowpath'] != tag:
                    continue
                # Find which pipe and compute section boundary
                for pipe in fp['pipes']:
                    if pipe['label'] == valve['pipe_label']:
                        sec = max(1, int(valve['position'] * pipe['nsegment']))
                        sec = min(sec, pipe['nsegment'])
                        fp_lines.append(
                            f' VALVE LABEL="{valve["label"]}", '
                            f'TIME=0 s, '
                            f'PIPE={valve["pipe_label"]}, '
                            f'SECTIONBOUNDARY={sec}, '
                            f'DIAMETER={_fmt_num_unit(pipe["diameter"], "m")}, '
                            f'OPENING={_fmt_scalar(valve["opening"])}'
                        )
                        break

            # Profile/trend data inside flowpath
            if self._profile_vars:
                var_str = f"({', '.join(self._profile_vars)})"
                fp_lines.append(f' PROFILEDATA VARIABLE={var_str}')

            # TRENDDATA at the outlet position gives the TPL its time series.
            if self._trend_vars and fp['pipes']:
                t_str = _fmt_str_tuple(self._trend_vars) if any(
                    ' ' in v for v in self._trend_vars
                ) else f"({', '.join(self._trend_vars)})"
                fp_lines.append(
                    f' TRENDDATA POSITION="POS_{tag}", VARIABLE={t_str}'
                )

            fp_lines.append("ENDNETWORKCOMPONENT")
            blocks.append("\n".join(fp_lines))

        return "\n\n".join(blocks)

    def _build_nodes(self):
        if not self._nodes:
            return ""
        blocks = []
        for tag, node in self._nodes.items():
            node_lines = []
            node_lines.append(f"NETWORKCOMPONENT TYPE=NODE, TAG={tag}")

            # Build PARAMETERS line
            params = [f'LABEL="{node["label"]}"', f'TYPE={node["node_type"]}']
            params.append("X=0 m, Y=0 m, Z=0 m")

            if node['node_type'] == 'PRESSURE':
                if node['pressure'] is not None:
                    params.append(
                        f'PRESSURE={_fmt_num_unit(node["pressure"], "Pa")}'
                    )
                if node['temperature'] is not None:
                    params.append(
                        f'TEMPERATURE={_fmt_num_unit(node["temperature"], "C")}'
                    )
                if node['gasfraction'] is not None:
                    params.append(
                        f'GASFRACTION={_fmt_scalar(node["gasfraction"])} -'
                    )
                params.append(f"TIME=0 s, FLUID={self._fluid_ref()}")

            node_lines.append(f' PARAMETERS {", ".join(params)}')
            node_lines.append("ENDNETWORKCOMPONENT")
            blocks.append("\n".join(node_lines))

        return "\n\n".join(blocks)

    def _build_connections(self):
        if not self._connections:
            return ""
        lines = []
        for comp1, term1, comp2, term2 in self._connections:
            lines.append(
                f"CONNECTION TERMINALS = ({comp1} {term1}, {comp2} {term2})"
            )
        return "\n".join(lines)

    def _build_reservoir_contacts(self):
        if not self._reservoir_contacts:
            return ""
        lines = []
        for rc in self._reservoir_contacts:
            iso = "YES" if rc['isothermal'] else "NO"
            lines.append(
                f'RESERVOIRCONTACT LABEL={rc["label"]}, '
                f'PIPE={rc["pipe_label"]}, '
                f'INTERPOLATION=OFF, '
                f'ISOTHERMAL={iso}'
            )
        return "\n".join(lines)

    def _build_linear_iprs(self):
        if not self._linear_iprs:
            return ""
        lines = []
        for ipr in self._linear_iprs:
            lines.append(
                f'LINEAR LABEL={ipr["label"]}, '
                f'TIME={_fmt_scalar(ipr["time"])} s, '
                f'MODELOPTION={ipr["model_option"]}, '
                f'A={_fmt_scalar(ipr["a"])} kg/s, '
                f'B={_fmt_scalar(ipr["b"])} kg/s-Pa'
            )
        return "\n".join(lines)

    def set_server_options(self, model_name, server_name='OLGAOPCServer', mode='SIMULATOR'):
        self._server_options = {
            'model_name': model_name,
            'server_name': server_name,
            'mode': mode
        }

    def set_server_data(self, variables, dtplot=1.0):
        self._server_data = {
            'variables': variables,  # list of strings
            'dtplot': dtplot
        }

    def _build_server_options(self):
        if not self._server_options:
            return ''
        so = self._server_options
        return 'SERVEROPTIONS MODELNAME=%s, SERVERNAME=%s, SIMULATORMODE=%s' % (
            so['model_name'], so['server_name'], so['mode'])

    def _build_server_data(self):
        if not self._server_data:
            return ''
        sd = self._server_data
        vars_str = ', '.join(sd['variables'])
        return 'SERVERDATA VARIABLE=(%s), DTPLOT=%s s' % (vars_str, sd['dtplot'])

    # ------------------------------------------------------------------
    # Topology templates
    # ------------------------------------------------------------------

    def _template_simple_pipeline(self):
        """1 flowpath, 3 pipes, 2 pressure nodes. Horizontal, 1000m total."""
        self._endtime = 3600.0
        self._steadystate = True

        self.add_material('Steel', conductivity=50.0, capacity=500.0,
                          density=7850.0)
        self.add_wall('Steel_Wall', [0.01], ['Steel'])

        # 3 pipes, each ~333m, horizontal
        seg_len = [66.6, 66.6, 66.6, 66.6, 66.6]  # 5 segments of 66.6m = 333m
        zero_elev = [0.0, 0.0, 0.0, 0.0, 0.0]

        self.add_pipe('FLOWPATH_1', 'Pipe_1', diameter=0.3,
                      lsegment=seg_len, elevation=zero_elev,
                      wall='Steel_Wall')
        self.add_pipe('FLOWPATH_1', 'Pipe_2', diameter=0.3,
                      lsegment=seg_len, elevation=zero_elev,
                      wall='Steel_Wall')
        self.add_pipe('FLOWPATH_1', 'Pipe_3', diameter=0.3,
                      lsegment=seg_len, elevation=zero_elev,
                      wall='Steel_Wall')

        self._flowpaths['FLOWPATH_1']['label'] = 'Pipeline'

        # Boundary nodes: 20 bara = 2e6 Pa, 10 bara = 1e6 Pa
        self.add_node('NODE_INLET', 'PRESSURE',
                      pressure=2e6, temperature=20.0, gasfraction=0.0)
        self.add_node('NODE_OUTLET', 'PRESSURE',
                      pressure=1e6, temperature=15.0, gasfraction=0.0)

        self.add_connection('NODE_INLET', 'FLOWTERM_1', 'FLOWPATH_1', 'INLET')
        self.add_connection('NODE_OUTLET', 'FLOWTERM_1', 'FLOWPATH_1', 'OUTLET')

    def _template_production_well(self):
        """1 vertical flowpath from reservoir to wellhead. 3000m TVD."""
        self._endtime = 86400.0
        # The bottomhole node is CLOSED and the template ships no inflow, so
        # the steady-state preprocessor would abort ("a source with non-zero
        # flow must exist at the first section"). Start transient instead; add
        # a SOURCE or a reservoir inflow before turning STEADYSTATE back on.
        self._steadystate = False
        self._dtstart = 0.01
        self._maxdt = 10.0

        self.add_material('Steel', conductivity=50.0, capacity=500.0,
                          density=7850.0)
        self.add_material('Cement', conductivity=1.0, capacity=2000.0,
                          density=1900.0)
        self.add_material('Rock', conductivity=2.5, capacity=800.0,
                          density=2600.0)

        self.add_wall('Tubing_Wall', [0.005, 0.02, 0.05],
                      ['Steel', 'Cement', 'Rock'])

        # Vertical well: 6 pipes, each 500m, going upward (negative to positive Z)
        # Listed bottom to top (inlet=bottom, outlet=top)
        n_pipes = 6
        seg_per_pipe = 5
        seg_len = 100.0  # each segment 100m -> 500m per pipe
        for i in range(n_pipes):
            pipe_label = f'Pipe_{i + 1}'
            lseg = [seg_len] * seg_per_pipe
            # Elevation: going up, so positive elevation change
            elev = [seg_len] * seg_per_pipe
            self.add_pipe('FLOWPATH_1', pipe_label, diameter=0.1,
                          lsegment=lseg, elevation=elev,
                          wall='Tubing_Wall', roughness=5e-5)

        self._flowpaths['FLOWPATH_1']['label'] = 'Tubing'

        # Bottom: CLOSED node (reservoir contact provides inflow)
        self.add_node('NODE_BH', 'CLOSED')

        # Top: PRESSURE node at wellhead
        # 300 bara reservoir -> 50 bara wellhead
        self.add_node('NODE_WH', 'PRESSURE',
                      pressure=5e6, temperature=15.0, gasfraction=0.5)

        self.add_connection('NODE_BH', 'FLOWTERM_1', 'FLOWPATH_1', 'INLET')
        self.add_connection('NODE_WH', 'FLOWTERM_1', 'FLOWPATH_1', 'OUTLET')

    def _template_well_pipeline(self):
        """2 flowpaths: vertical well + horizontal pipeline. 3 nodes."""
        self._endtime = 86400.0
        # Same reason as production_well: the reservoir node is CLOSED and no
        # inflow is defined, which the steady-state preprocessor rejects.
        self._steadystate = False
        self._dtstart = 0.01
        self._maxdt = 10.0

        self.add_material('Steel', conductivity=50.0, capacity=500.0,
                          density=7850.0)
        self.add_wall('Steel_Wall', [0.01], ['Steel'])

        # Well: 4 pipes, 500m each, vertical
        seg_per_pipe = 5
        for i in range(4):
            lseg = [100.0] * seg_per_pipe
            elev = [100.0] * seg_per_pipe
            self.add_pipe('FP_WELL', f'WPipe_{i + 1}', diameter=0.1,
                          lsegment=lseg, elevation=elev,
                          wall='Steel_Wall')
        self._flowpaths['FP_WELL']['label'] = 'Well_Tubing'

        # Pipeline: 5 pipes, 1000m each, horizontal
        for i in range(5):
            lseg = [200.0] * seg_per_pipe
            elev = [0.0] * seg_per_pipe
            self.add_pipe('FP_PIPE', f'PPipe_{i + 1}', diameter=0.3,
                          lsegment=lseg, elevation=elev,
                          wall='Steel_Wall')
        self._flowpaths['FP_PIPE']['label'] = 'Pipeline'

        self.add_node('NODE_RES', 'CLOSED')
        self.add_node('NODE_WH', 'PRESSURE',
                      pressure=5e6, temperature=60.0, gasfraction=0.3)
        self.add_node('NODE_SEP', 'PRESSURE',
                      pressure=1e6, temperature=30.0, gasfraction=0.0)

        self.add_connection('NODE_RES', 'FLOWTERM_1', 'FP_WELL', 'INLET')
        self.add_connection('NODE_WH', 'FLOWTERM_1', 'FP_WELL', 'OUTLET')
        self.add_connection('NODE_WH', 'FLOWTERM_2', 'FP_PIPE', 'INLET')
        self.add_connection('NODE_SEP', 'FLOWTERM_1', 'FP_PIPE', 'OUTLET')

    def _template_subsea_tieback(self):
        """3 flowpaths: flowline + riser + topside. 4 nodes."""
        self._endtime = 86400.0
        self._steadystate = True
        self._maxdt = 5.0

        self.add_material('Steel', conductivity=50.0, capacity=500.0,
                          density=7850.0)
        self.add_material('Insulation', conductivity=0.15, capacity=1500.0,
                          density=900.0)
        self.add_wall('Insulated_Wall', [0.01, 0.04], ['Steel', 'Insulation'])
        self.add_wall('Steel_Wall', [0.01], ['Steel'])

        seg_per_pipe = 5

        # Flowline: 10km horizontal, 5 pipes of 2km each
        for i in range(5):
            lseg = [400.0] * seg_per_pipe
            elev = [0.0] * seg_per_pipe
            self.add_pipe('FP_FLOWLINE', f'FL_Pipe_{i + 1}', diameter=0.2,
                          lsegment=lseg, elevation=elev,
                          wall='Insulated_Wall')
        self._flowpaths['FP_FLOWLINE']['label'] = 'Flowline'

        # Riser: 500m vertical, 2 pipes of 250m each
        for i in range(2):
            lseg = [50.0] * seg_per_pipe
            elev = [50.0] * seg_per_pipe
            self.add_pipe('FP_RISER', f'RS_Pipe_{i + 1}', diameter=0.2,
                          lsegment=lseg, elevation=elev,
                          wall='Steel_Wall')
        self._flowpaths['FP_RISER']['label'] = 'Riser'

        # Topside: 100m horizontal
        lseg = [20.0] * seg_per_pipe
        elev = [0.0] * seg_per_pipe
        self.add_pipe('FP_TOPSIDE', 'TS_Pipe_1', diameter=0.2,
                      lsegment=lseg, elevation=elev,
                      wall='Steel_Wall')
        self._flowpaths['FP_TOPSIDE']['label'] = 'Topside'

        self.add_node('NODE_WH', 'PRESSURE',
                      pressure=10e6, temperature=80.0, gasfraction=0.3)
        self.add_node('NODE_RBASE', 'PRESSURE',
                      pressure=8e6, temperature=60.0, gasfraction=0.3)
        self.add_node('NODE_PLATF', 'PRESSURE',
                      pressure=3e6, temperature=40.0, gasfraction=0.3)
        self.add_node('NODE_SEP', 'PRESSURE',
                      pressure=2e6, temperature=35.0, gasfraction=0.0)

        self.add_connection('NODE_WH', 'FLOWTERM_1', 'FP_FLOWLINE', 'INLET')
        self.add_connection('NODE_RBASE', 'FLOWTERM_1', 'FP_FLOWLINE', 'OUTLET')
        self.add_connection('NODE_RBASE', 'FLOWTERM_2', 'FP_RISER', 'INLET')
        self.add_connection('NODE_PLATF', 'FLOWTERM_1', 'FP_RISER', 'OUTLET')
        self.add_connection('NODE_PLATF', 'FLOWTERM_2', 'FP_TOPSIDE', 'INLET')
        self.add_connection('NODE_SEP', 'FLOWTERM_1', 'FP_TOPSIDE', 'OUTLET')

    def _template_riser(self):
        """1 vertical flowpath, 2 nodes. 500m riser."""
        self._endtime = 3600.0
        self._steadystate = True

        self.add_material('Steel', conductivity=50.0, capacity=500.0,
                          density=7850.0)
        self.add_wall('Steel_Wall', [0.012], ['Steel'])

        seg_per_pipe = 5
        # 5 pipes of 100m each, vertical
        for i in range(5):
            lseg = [20.0] * seg_per_pipe
            elev = [20.0] * seg_per_pipe
            self.add_pipe('FLOWPATH_1', f'Riser_Pipe_{i + 1}', diameter=0.2,
                          lsegment=lseg, elevation=elev,
                          wall='Steel_Wall')
        self._flowpaths['FLOWPATH_1']['label'] = 'Riser'

        self.add_node('NODE_SEABED', 'PRESSURE',
                      pressure=5e6, temperature=4.0, gasfraction=0.3)
        self.add_node('NODE_TOPSIDE', 'PRESSURE',
                      pressure=2e6, temperature=20.0, gasfraction=0.0)

        self.add_connection('NODE_SEABED', 'FLOWTERM_1', 'FLOWPATH_1', 'INLET')
        self.add_connection('NODE_TOPSIDE', 'FLOWTERM_1', 'FLOWPATH_1', 'OUTLET')

    def _template_separator(self):
        """3 flowpaths: inlet, gas outlet, liquid outlet. Separator at junction."""
        self._endtime = 7200.0
        self._steadystate = True

        self.add_material('Steel', conductivity=50.0, capacity=500.0,
                          density=7850.0)
        self.add_wall('Steel_Wall', [0.01], ['Steel'])

        seg_per_pipe = 5

        # Inlet flowpath: 200m horizontal
        lseg = [40.0] * seg_per_pipe
        elev = [0.0] * seg_per_pipe
        self.add_pipe('FP_INLET', 'Inlet_Pipe_1', diameter=0.3,
                      lsegment=lseg, elevation=elev,
                      wall='Steel_Wall')
        self._flowpaths['FP_INLET']['label'] = 'Inlet_Line'

        # Gas outlet: 100m horizontal
        lseg_g = [20.0] * seg_per_pipe
        elev_g = [0.0] * seg_per_pipe
        self.add_pipe('FP_GAS', 'Gas_Pipe_1', diameter=0.2,
                      lsegment=lseg_g, elevation=elev_g,
                      wall='Steel_Wall')
        self._flowpaths['FP_GAS']['label'] = 'Gas_Outlet'

        # Liquid outlet: 100m horizontal
        self.add_pipe('FP_LIQ', 'Liq_Pipe_1', diameter=0.15,
                      lsegment=lseg_g, elevation=elev_g,
                      wall='Steel_Wall')
        self._flowpaths['FP_LIQ']['label'] = 'Liquid_Outlet'

        self.add_node('NODE_FEED', 'PRESSURE',
                      pressure=5e6, temperature=60.0, gasfraction=0.5)
        self.add_node('NODE_SEP', 'PRESSURE',
                      pressure=3e6, temperature=50.0, gasfraction=0.5)
        self.add_node('NODE_GAS_OUT', 'PRESSURE',
                      pressure=2.5e6, temperature=45.0, gasfraction=1.0)
        self.add_node('NODE_LIQ_OUT', 'PRESSURE',
                      pressure=2.8e6, temperature=45.0, gasfraction=0.0)

        self.add_connection('NODE_FEED', 'FLOWTERM_1', 'FP_INLET', 'INLET')
        self.add_connection('NODE_SEP', 'FLOWTERM_1', 'FP_INLET', 'OUTLET')
        self.add_connection('NODE_SEP', 'FLOWTERM_2', 'FP_GAS', 'INLET')
        self.add_connection('NODE_GAS_OUT', 'FLOWTERM_1', 'FP_GAS', 'OUTLET')
        self.add_connection('NODE_SEP', 'FLOWTERM_3', 'FP_LIQ', 'INLET')
        self.add_connection('NODE_LIQ_OUT', 'FLOWTERM_1', 'FP_LIQ', 'OUTLET')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _safe_print(text):
    """Print text safely on Windows cp949 terminals."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('ascii', errors='replace').decode('ascii'))


def main():
    parser = argparse.ArgumentParser(
        description="Build OLGA .genkey simulation files from topology templates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Topologies:\n"
            "  simple_pipeline   - Horizontal pipeline (3 pipes, 2 nodes)\n"
            "  production_well   - Vertical well (6 pipes, reservoir to wellhead)\n"
            "  well_pipeline     - Well + surface pipeline (2 flowpaths)\n"
            "  subsea_tieback    - Flowline + riser + topside (3 flowpaths)\n"
            "  riser             - Vertical riser (5 pipes, seabed to topside)\n"
            "  separator         - 3-way separator (inlet + gas/liquid outlets)\n"
        ),
    )
    parser.add_argument(
        "topology", nargs="?", default=None,
        help="Topology template name",
    )
    parser.add_argument(
        "--list-topologies", action="store_true",
        help="List available topologies and exit",
    )
    parser.add_argument("--save", default=None, help="Output .genkey file path")
    parser.add_argument("--json", action="store_true",
                        help="Print the genkey text to stdout")
    parser.add_argument("--endtime", type=float, default=None,
                        help="Override simulation end time (seconds)")
    parser.add_argument("--fluid-label", default=None,
                        help="Fluid tag for BRANCH/NODE FLUID (default: read "
                             "the label from the .tab)")
    parser.add_argument("--pvtfile", default=None,
                        help="Override PVT file path")
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip post-build validation")

    args = parser.parse_args()

    if args.list_topologies:
        _safe_print("Available topologies:")
        for t in TOPOLOGIES:
            _safe_print(f"  {t}")
        sys.exit(0)

    if args.topology is None:
        parser.print_help()
        sys.exit(2)

    if args.topology not in TOPOLOGIES:
        _safe_print(f"Error: unknown topology '{args.topology}'")
        _safe_print(f"Choose from: {', '.join(TOPOLOGIES)}")
        sys.exit(2)

    builder = GenkeyBuilder(args.topology)

    if args.endtime is not None:
        builder.set_simulation(
            endtime=args.endtime,
            dtstart=builder._dtstart,
            mindt=builder._mindt,
            maxdt=builder._maxdt,
            steadystate=builder._steadystate,
            starttime=builder._starttime,
        )
    if args.pvtfile is not None:
        builder.set_fluid(args.pvtfile)

    if args.fluid_label is not None:
        builder.set_fluid_label(args.fluid_label)

    # Resolve a relative PVT reference against the output directory so the
    # fluid label is available during the pre-save validation pass too.
    if args.save:
        builder._output_dir = Path(args.save).parent

    # Build
    text = builder.build()

    # Validate unless skipped
    if not args.no_validate:
        errors, warnings, findings = builder.validate()
        if errors:
            _safe_print("Validation ERRORS in generated file:")
            for e in errors:
                _safe_print(f"  [{e['rule_id']}] {e['message']}")
            sys.exit(1)
        if warnings:
            _safe_print("Validation warnings:")
            for w in warnings:
                _safe_print(f"  [{w['rule_id']}] {w['message']}")

    if args.json:
        _safe_print(text)

    if args.save:
        builder.save(args.save)
        _safe_print(f"Saved: {args.save}")

    if not args.json and not args.save:
        _safe_print(text)

    sys.exit(0)


if __name__ == "__main__":
    main()
