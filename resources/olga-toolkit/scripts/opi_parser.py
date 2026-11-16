"""
opi_parser.py -- Parse OLGA .opi XML project layout files.

Usage:
    python opi_parser.py file.opi
    python opi_parser.py file.opi --list-components
    python opi_parser.py file.opi --json

Exit codes:
    0 = success
    1 = general error
    2 = parse / file error
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


class OpiParser:
    """Parse an OLGA .opi XML layout file."""

    def __init__(self, opi_path):
        """Read and parse .opi XML file.

        Raises IOError on file access failure, ET.ParseError on malformed XML.
        """
        self.path = Path(opi_path)
        try:
            self._tree = ET.parse(str(self.path))
        except OSError as exc:
            raise IOError("Cannot open file: {}".format(exc)) from exc
        self._root = self._tree.getroot()

    # -----------------------------------------------------------------------
    # Public methods
    # -----------------------------------------------------------------------

    def get_olga_version(self):
        """Return version string 'MajorVersion.MinorVersion.BuildVersion'.

        Returns None if version attributes are missing.
        """
        major = self._root.get('MajorVersion')
        minor = self._root.get('MinorVersion')
        build = self._root.get('BuildVersion')
        if major is None:
            return None
        parts = [major, minor, build]
        return '.'.join(p for p in parts if p is not None)

    def list_components(self):
        """Return sorted list of all VisualObject Id strings."""
        ids = []
        for vo in self._root.iter('VisualObject'):
            vid = vo.get('Id')
            if vid is not None:
                ids.append(vid)
        return sorted(ids)

    def get_visual_objects(self):
        """Return list of dicts describing each VisualObject.

        Each dict:
            {
                'id': str,
                'bounds': {'top': float, 'left': float,
                           'width': float, 'height': float},
                'control_points': [(x, y), ...]
            }

        'bounds' is None if the element is absent.
        'control_points' is an empty list if absent.
        """
        objects = []
        for vo in self._root.iter('VisualObject'):
            vid = vo.get('Id')
            if vid is None:
                continue

            bounds = None
            bounds_el = vo.find('Bounds')
            if bounds_el is not None:
                bounds = {
                    'top': _parse_float(bounds_el.get('top')),
                    'left': _parse_float(bounds_el.get('left')),
                    'width': _parse_float(bounds_el.get('width')),
                    'height': _parse_float(bounds_el.get('height')),
                }

            control_points = []
            cp_el = vo.find('ControlPoints')
            if cp_el is not None:
                for pt in cp_el.findall('PointF'):
                    # Points use child elements <X> and <Y>
                    x_el = pt.find('X')
                    y_el = pt.find('Y')
                    if x_el is not None and y_el is not None:
                        x = _parse_float(x_el.text)
                        y = _parse_float(y_el.text)
                        control_points.append((x, y))
                    else:
                        # Fallback: attributes X/Y (spec variant)
                        x = _parse_float(pt.get('X'))
                        y = _parse_float(pt.get('Y'))
                        if x is not None or y is not None:
                            control_points.append((x, y))

            objects.append({
                'id': vid,
                'bounds': bounds,
                'control_points': control_points,
            })
        return objects

    def to_dict(self):
        """Return full parsed content as a plain dict."""
        return {
            'file': str(self.path),
            'version': self.get_olga_version(),
            'components': self.list_components(),
            'visual_objects': self.get_visual_objects(),
        }

    def to_json(self, indent=2):
        """Return JSON string of to_dict()."""
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_float(s):
    """Parse a float string; return None on failure."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    p = argparse.ArgumentParser(
        description='Parse OLGA .opi XML project layout files.'
    )
    p.add_argument('opi_file', help='Path to the OLGA .opi file')
    p.add_argument('--list-components', action='store_true',
                   help='Print all VisualObject IDs and exit')
    p.add_argument('--json', action='store_true',
                   help='Output full parsed content as JSON')
    return p


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    parser = _build_parser()
    args = parser.parse_args()

    opi_path = args.opi_file
    if not os.path.isfile(opi_path):
        print('Error: file not found: {}'.format(opi_path), file=sys.stderr)
        sys.exit(2)

    try:
        opi = OpiParser(opi_path)
    except (IOError, ET.ParseError) as exc:
        print('Parse error: {}'.format(exc), file=sys.stderr)
        sys.exit(2)

    try:
        if args.json:
            print(opi.to_json())
        elif args.list_components:
            for cid in opi.list_components():
                print(cid)
        else:
            version = opi.get_olga_version()
            components = opi.list_components()
            print('File   : {}'.format(opi.path.name))
            print('Version: {}'.format(version or 'unknown'))
            print('Components ({} total):'.format(len(components)))
            for cid in components:
                print('  {}'.format(cid))
    except Exception as exc:
        print('Error: {}'.format(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
