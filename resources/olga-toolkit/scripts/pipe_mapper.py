"""
pipe_mapper.py -- Section-to-pipe mapping tool for OLGA simulations.

Maps PPL section indices to genkey PIPE labels within a flowpath,
enabling pipe-level analysis of profile data.

Usage as a library:
    from pipe_mapper import PipeMapper
    pm = PipeMapper('model.genkey', 'FLOWPATH_322')
    pipes = pm.list_pipes()
    start, end = pm.get_section_range('PIPE-7')
    vol = pm.get_pipe_volume('PIPE-7')
    liqc = pm.compute_pipe_liqc(hol_array, 'PIPE-7')

Standalone usage:
    python pipe_mapper.py model.genkey FLOWPATH_322 --list-pipes
    python pipe_mapper.py model.genkey FLOWPATH_322 --pipe PIPE-7 --sections
    python pipe_mapper.py model.genkey FLOWPATH_322 --pipe PIPE-7 --volume
    python pipe_mapper.py model.genkey FLOWPATH_322 --elevation-profile
    python pipe_mapper.py model.genkey FLOWPATH_322 --lowest-point
    python pipe_mapper.py model.genkey FLOWPATH_322 --json
"""

import math
import os
import sys
import json
import argparse

# ---------------------------------------------------------------------------
# Ensure genkey_parser is importable (same scripts/ directory)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from genkey_parser import GenkeyParser

# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
_LENGTH_TO_M = {
    'm': 1.0, 'M': 1.0,
    'mm': 0.001, 'MM': 0.001,
    'ft': 0.3048, 'FT': 0.3048,
    'in': 0.0254, 'IN': 0.0254,
    'cm': 0.01, 'CM': 0.01,
}


class PipeMapper:
    """Map PPL section indices to genkey PIPE labels within a flowpath.

    Parameters
    ----------
    genkey_path : str
        Path to .genkey file.
    flowpath_label : str
        Flowpath TAG or LABEL to analyze.
    """

    def __init__(self, genkey_path, flowpath_label):
        gk = GenkeyParser(genkey_path)
        fp = self._find_flowpath(gk.flowpaths, flowpath_label)
        if fp is None:
            raise ValueError(
                'Flowpath not found: %s' % flowpath_label
            )

        self._pipes = []
        section_offset = 0
        # OLGA's vertical axis is Y: a coordinate-form pipe (XEND/YEND/ZEND)
        # carries its elevation in Y, starting from the GEOMETRY start point.
        previous_y = 0.0
        for child in fp['children']:
            if child['keyword'] == 'GEOMETRY':
                previous_y = self._y_metres(child['params'], 'YSTART', previous_y)
                break

        for child in fp['children']:
            if child['keyword'] != 'PIPE':
                continue
            params = child['params']

            label = params.get('LABEL', 'UNKNOWN')
            diameter_m = self._to_metres_param(params.get('DIAMETER', 0.0))
            lsegment_raw = params.get('LSEGMENT', [])
            lsegment_m = self._parse_lsegment(lsegment_raw)
            nsegment = self._compute_nsegment(params, lsegment_raw)
            elevation_raw = params.get('ELEVATION', [])
            if 'ELEVATION' in params:
                elevation_m = self._parse_elevation(elevation_raw)
            elif 'YEND' in params:
                start_y = self._y_metres(params, 'YSTART', previous_y)
                start_y = self._y_metres(params, 'Y', start_y)
                previous_y = self._y_metres(params, 'YEND', start_y)
                elevation_m = [start_y, previous_y]
            else:
                elevation_m = []

            total_length = sum(lsegment_m)
            area = math.pi / 4.0 * diameter_m ** 2
            volume_m3 = area * total_length

            # Section volumes (per-segment)
            section_volumes = [area * ls for ls in lsegment_m]

            section_start = section_offset
            section_end = section_offset + nsegment - 1
            section_offset += nsegment

            self._pipes.append({
                'label': label,
                'nsegment': nsegment,
                'diameter_m': diameter_m,
                'lsegment_m': lsegment_m,
                'elevation_m': elevation_m,
                'total_length_m': total_length,
                'volume_m3': volume_m3,
                'section_volumes_m3': section_volumes,
                'section_start': section_start,
                'section_end': section_end,
            })

        self._label_index = {
            p['label']: i for i, p in enumerate(self._pipes)
        }

    # ------------------------------------------------------------------
    # Flowpath lookup
    # ------------------------------------------------------------------

    def _y_metres(self, params, key, default):
        """Return params[key] in metres, or default when the key is absent."""
        if key not in params:
            return default
        return self._to_metres_param(params[key])

    @staticmethod
    def _find_flowpath(flowpaths, label):
        """Find flowpath by TAG (case-insensitive), with BRANCH LABEL fallback."""
        label_upper = label.upper()
        for fp in flowpaths:
            if fp.get('tag', '').upper() == label_upper:
                return fp
        # Fallback: check BRANCH child LABEL
        for fp in flowpaths:
            for child in fp.get('children', []):
                if child['keyword'] == 'BRANCH':
                    branch_label = child['params'].get('LABEL', '')
                    if branch_label.upper() == label_upper:
                        return fp
        return None

    # ------------------------------------------------------------------
    # Value extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_value(param, default=None):
        """Extract numeric value from param that may be plain or dict with value/unit."""
        if param is None:
            return default
        if isinstance(param, dict) and 'value' in param:
            return param['value']
        return param

    @staticmethod
    def _extract_unit(param):
        """Extract unit string from param, or None."""
        if isinstance(param, dict) and 'unit' in param:
            return param['unit']
        return None

    @staticmethod
    def _to_metres(value, unit):
        """Convert a length value to metres."""
        if unit is None:
            return float(value)
        factor = _LENGTH_TO_M.get(unit)
        if factor is None:
            return float(value)
        return float(value) * factor

    def _to_metres_param(self, param):
        """Convert a single-value param (possibly with unit) to metres."""
        value = self._extract_value(param, 0.0)
        unit = self._extract_unit(param)
        return self._to_metres(value, unit)

    def _parse_lsegment(self, raw):
        """Parse LSEGMENT param into a list of segment lengths in metres."""
        value = self._extract_value(raw, [])
        unit = self._extract_unit(raw)
        if isinstance(value, list):
            return [self._to_metres(v, unit) for v in value]
        # Single value
        return [self._to_metres(value, unit)]

    def _parse_elevation(self, raw):
        """Parse ELEVATION param into a list of elevations in metres."""
        value = self._extract_value(raw, [])
        unit = self._extract_unit(raw)
        if isinstance(value, list):
            return [self._to_metres(v, unit) for v in value]
        return [self._to_metres(value, unit)]

    @staticmethod
    def _compute_nsegment(params, lsegment_raw):
        """Compute number of segments from explicit NSEGMENT or LSEGMENT length."""
        if 'NSEGMENT' in params:
            val = params['NSEGMENT']
            if isinstance(val, dict) and 'value' in val:
                return int(val['value'])
            return int(val)
        # Derive from LSEGMENT
        value = lsegment_raw
        if isinstance(value, dict) and 'value' in value:
            value = value['value']
        if isinstance(value, list):
            return len(value)
        return 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _get_pipe(self, pipe_label):
        """Return pipe dict by label, or raise ValueError."""
        idx = self._label_index.get(pipe_label)
        if idx is None:
            raise ValueError('Pipe not found: %s' % pipe_label)
        return self._pipes[idx]

    def get_section_range(self, pipe_label):
        """Return (start, end) 0-indexed section range for a pipe (inclusive)."""
        p = self._get_pipe(pipe_label)
        return (p['section_start'], p['section_end'])

    def get_pipe_volume(self, pipe_label):
        """Return pipe volume in m3. Formula: pi/4 * D^2 * sum(LSEGMENT)."""
        return self._get_pipe(pipe_label)['volume_m3']

    def get_elevation_profile(self):
        """Return list of dicts with pipe_label, start_pos, end_pos, start_elev, end_elev."""
        profile = []
        pos = 0.0
        for p in self._pipes:
            start_pos = pos
            end_pos = pos + p['total_length_m']
            elevations = p['elevation_m']
            start_elev = elevations[0] if elevations else 0.0
            end_elev = elevations[-1] if elevations else 0.0
            profile.append({
                'pipe_label': p['label'],
                'start_pos': start_pos,
                'end_pos': end_pos,
                'start_elev': start_elev,
                'end_elev': end_elev,
            })
            pos = end_pos
        return profile

    def get_lowest_point(self):
        """Return (description, elevation_m) for the minimum elevation point."""
        min_elev = float('inf')
        min_desc = ''
        for p in self._pipes:
            for i, elev in enumerate(p['elevation_m']):
                if elev < min_elev:
                    min_elev = elev
                    min_desc = '%s elevation[%d]' % (p['label'], i)
        if min_elev == float('inf'):
            return ('no elevation data', 0.0)
        return (min_desc, min_elev)

    def compute_pipe_liqc(self, hol_array, pipe_label):
        """Compute liquid content in litres for a pipe given HOL array from PPL.

        For each section i in pipe range:
            LIQC += HOL[i] * V_section[i]
        where V_section = pi/4 * D^2 * L_section

        Returns float in litres (m3 * 1000).
        """
        p = self._get_pipe(pipe_label)
        start = p['section_start']
        end = p['section_end']
        section_vols = p['section_volumes_m3']

        liqc_m3 = 0.0
        for i, sec_idx in enumerate(range(start, end + 1)):
            if sec_idx < len(hol_array) and i < len(section_vols):
                liqc_m3 += float(hol_array[sec_idx]) * section_vols[i]

        return liqc_m3 * 1000.0

    def list_pipes(self):
        """Return list of pipe metadata dicts."""
        result = []
        for p in self._pipes:
            result.append({
                'label': p['label'],
                'nsegment': p['nsegment'],
                'diameter_m': p['diameter_m'],
                'total_length_m': p['total_length_m'],
                'volume_m3': p['volume_m3'],
                'volume_litres': p['volume_m3'] * 1000.0,
                'section_range': (p['section_start'], p['section_end']),
            })
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace('-', '') != 'utf8':
        import io
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace'
        )

    ap = argparse.ArgumentParser(
        description='Map PPL section indices to genkey PIPE labels'
    )
    ap.add_argument('genkey', help='Path to .genkey file')
    ap.add_argument('flowpath', help='Flowpath TAG or LABEL')
    ap.add_argument('--list-pipes', action='store_true',
                    help='List all pipes with metadata')
    ap.add_argument('--pipe', help='Target pipe label')
    ap.add_argument('--sections', action='store_true',
                    help='Show section range for --pipe')
    ap.add_argument('--volume', action='store_true',
                    help='Show volume for --pipe')
    ap.add_argument('--elevation-profile', action='store_true',
                    help='Show elevation profile for all pipes')
    ap.add_argument('--lowest-point', action='store_true',
                    help='Show lowest elevation point')
    ap.add_argument('--json', action='store_true',
                    help='Dump full pipe map as JSON')
    args = ap.parse_args()

    if not os.path.isfile(args.genkey):
        print('Error: file not found: %s' % args.genkey, file=sys.stderr)
        sys.exit(2)

    try:
        pm = PipeMapper(args.genkey, args.flowpath)
    except ValueError as e:
        print('Error: %s' % e, file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(pm.list_pipes(), indent=2, default=str))
        sys.exit(0)

    if args.list_pipes:
        pipes = pm.list_pipes()
        print('%-16s %6s %10s %10s %10s %10s  %s' % (
            'LABEL', 'NSEG', 'DIA(mm)', 'LEN(m)', 'VOL(m3)', 'VOL(L)',
            'SECTIONS'))
        print('-' * 85)
        for p in pipes:
            s, e = p['section_range']
            print('%-16s %6d %10.2f %10.3f %10.6f %10.3f  %d-%d' % (
                p['label'], p['nsegment'],
                p['diameter_m'] * 1000.0,
                p['total_length_m'],
                p['volume_m3'],
                p['volume_litres'],
                s, e))
        sys.exit(0)

    if args.elevation_profile:
        profile = pm.get_elevation_profile()
        print('%-16s %10s %10s %10s %10s' % (
            'PIPE', 'START(m)', 'END(m)', 'ELEV_S(m)', 'ELEV_E(m)'))
        print('-' * 60)
        for entry in profile:
            print('%-16s %10.3f %10.3f %10.3f %10.3f' % (
                entry['pipe_label'],
                entry['start_pos'], entry['end_pos'],
                entry['start_elev'], entry['end_elev']))
        sys.exit(0)

    if args.lowest_point:
        desc, elev = pm.get_lowest_point()
        print('Lowest point: %s at %.4f m' % (desc, elev))
        sys.exit(0)

    if args.pipe:
        if args.sections:
            s, e = pm.get_section_range(args.pipe)
            print('Pipe %s: sections %d-%d (%d sections)' % (
                args.pipe, s, e, e - s + 1))
            sys.exit(0)
        if args.volume:
            vol = pm.get_pipe_volume(args.pipe)
            print('Pipe %s: %.6f m3 (%.3f litres)' % (
                args.pipe, vol, vol * 1000.0))
            sys.exit(0)
        # Default: show both
        s, e = pm.get_section_range(args.pipe)
        vol = pm.get_pipe_volume(args.pipe)
        print('Pipe %s: sections %d-%d (%d sections), %.6f m3 (%.3f L)' % (
            args.pipe, s, e, e - s + 1, vol, vol * 1000.0))
        sys.exit(0)

    # No specific action requested -- show summary
    pipes = pm.list_pipes()
    total_sections = sum(p['nsegment'] for p in pipes)
    total_vol = sum(p['volume_m3'] for p in pipes)
    print('Flowpath: %s' % args.flowpath)
    print('  Pipes: %d' % len(pipes))
    print('  Total sections: %d' % total_sections)
    print('  Total volume: %.6f m3 (%.3f L)' % (total_vol, total_vol * 1000.0))


if __name__ == '__main__':
    main()
