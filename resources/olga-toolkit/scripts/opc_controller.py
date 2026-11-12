"""opc_controller.py - OPC-DA live control for OLGA simulations.

Connects to OLGA's OPC server for real-time variable reading/writing,
simulation control, and snapshot management.

Windows-only: OPC-DA uses COM/DCOM.
"""

import sys
import time
import argparse

try:
    import OpenOPC
    OPC_AVAILABLE = True
except ImportError:
    OPC_AVAILABLE = False

OLGA_OPC_SERVER = 'SPT.OLGAOPCServer.1'

_DCOM_HINT = (
    'If you see DCOM permission errors, use the dcomperm tools in your '
    'OLGA installation to grant access rights.'
)


class OpcController:
    """OPC-DA controller for OLGA simulations."""

    def __init__(self, server_name=OLGA_OPC_SERVER):
        if not OPC_AVAILABLE:
            raise ImportError(
                'OpenOPC is not installed. Run: pip install OpenOPC-Python3x'
            )
        self._server_name = server_name
        self._client = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self, timeout=10):
        """Connect to the OPC-DA server."""
        try:
            self._client = OpenOPC.client()
            self._client.connect(self._server_name, timeout=timeout)
        except Exception as exc:
            self._client = None
            msg = str(exc)
            if 'not found' in msg.lower() or 'progid' in msg.lower():
                available = self._list_servers()
                hint = (
                    'Available servers: ' + ', '.join(available)
                    if available
                    else 'No OPC servers found. Ensure OLGA is running in '
                         'server mode (SERVEROPTIONS in genkey).'
                )
                raise ConnectionError(
                    'OPC server not found: {}. {}'.format(
                        self._server_name, hint
                    )
                ) from exc
            if 'access' in msg.lower() or 'dcom' in msg.lower():
                raise PermissionError(
                    'DCOM access denied connecting to {}. {}'.format(
                        self._server_name, _DCOM_HINT
                    )
                ) from exc
            raise ConnectionError(
                'Failed to connect to {}: {}'.format(self._server_name, msg)
            ) from exc

    def disconnect(self):
        """Clean disconnect from OPC server."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            finally:
                self._client = None

    def is_connected(self):
        """Return True if currently connected to the OPC server."""
        if self._client is None:
            return False
        try:
            # list() with a short pattern is a lightweight liveness check
            self._client.list('*', flat=True)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Read / Write
    # ------------------------------------------------------------------

    def read(self, item):
        """Read a single OPC item.

        Returns (value, quality, timestamp).
        """
        self._require_connection()
        try:
            result = self._client.read(item)
            # OpenOPC returns (value, quality, timestamp)
            return result
        except Exception as exc:
            raise RuntimeError(
                'Failed to read {}: {}'.format(item, exc)
            ) from exc

    def read_multiple(self, items):
        """Batch-read OPC items.

        Returns list of (item, value, quality, timestamp).
        """
        self._require_connection()
        try:
            results = self._client.read(items)
            return results
        except Exception as exc:
            raise RuntimeError(
                'Failed to read items: {}'.format(exc)
            ) from exc

    def write(self, item, value):
        """Write a value to a single OPC item."""
        self._require_connection()
        try:
            self._client.write((item, value))
        except Exception as exc:
            raise RuntimeError(
                'Failed to write {}={}: {}'.format(item, value, exc)
            ) from exc

    def write_multiple(self, items_values):
        """Batch-write OPC items.

        items_values: list of (item, value) tuples.
        """
        self._require_connection()
        try:
            self._client.write(items_values)
        except Exception as exc:
            raise RuntimeError(
                'Failed to batch write: {}'.format(exc)
            ) from exc

    def list_items(self, pattern='*'):
        """List available OPC items matching pattern."""
        self._require_connection()
        try:
            return self._client.list(pattern, flat=True)
        except Exception as exc:
            raise RuntimeError(
                'Failed to list items: {}'.format(exc)
            ) from exc

    # ------------------------------------------------------------------
    # Simulation control
    # ------------------------------------------------------------------

    def pause(self):
        """Pause the OLGA simulation."""
        self._require_connection()
        try:
            self._client.write(('OLGA.COMMAND', 'PAUSE'))
        except Exception as exc:
            raise RuntimeError('Failed to pause simulation: {}'.format(exc)) from exc

    def resume(self):
        """Resume the OLGA simulation."""
        self._require_connection()
        try:
            self._client.write(('OLGA.COMMAND', 'RESUME'))
        except Exception as exc:
            raise RuntimeError('Failed to resume simulation: {}'.format(exc)) from exc

    def save_snapshot(self, name):
        """Save a simulation snapshot with the given name."""
        self._require_connection()
        try:
            self._client.write(('OLGA.SNAPSHOT.SAVE', name))
        except Exception as exc:
            raise RuntimeError(
                'Failed to save snapshot "{}": {}'.format(name, exc)
            ) from exc

    def load_snapshot(self, name):
        """Load a simulation snapshot by name."""
        self._require_connection()
        try:
            self._client.write(('OLGA.SNAPSHOT.LOAD', name))
        except Exception as exc:
            raise RuntimeError(
                'Failed to load snapshot "{}": {}'.format(name, exc)
            ) from exc

    def get_time(self):
        """Get the current simulation time (seconds)."""
        self._require_connection()
        try:
            value, _quality, _ts = self._client.read('OLGA.TIME')
            return value
        except Exception as exc:
            raise RuntimeError(
                'Failed to get simulation time: {}'.format(exc)
            ) from exc

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    def monitor(self, items, interval=1.0, duration=None, callback=None):
        """Live monitoring loop.

        Reads items every interval seconds. Calls callback(readings) if
        provided, otherwise prints to stdout. Runs until duration elapsed
        or Ctrl+C.
        """
        self._require_connection()
        if isinstance(items, str):
            items = [items]

        start = time.time()
        try:
            while True:
                readings = self.read_multiple(items)
                if callback is not None:
                    callback(readings)
                else:
                    ts = time.strftime('%H:%M:%S')
                    for entry in readings:
                        # entry: (item, value, quality, timestamp)
                        print('{} | {} = {} [{}]'.format(
                            ts, entry[0], entry[1], entry[2]
                        ))
                if duration is not None and (time.time() - start) >= duration:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            pass

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def status():
        """Check if any OPC servers are available on this machine.

        Returns dict with keys 'available' (bool) and 'servers' (list).
        """
        if not OPC_AVAILABLE:
            return {
                'available': False,
                'servers': [],
                'error': 'OpenOPC not installed. Run: pip install OpenOPC-Python3x',
            }
        try:
            servers = OpcController._list_servers()
            return {'available': bool(servers), 'servers': servers}
        except Exception as exc:
            return {'available': False, 'servers': [], 'error': str(exc)}

    @staticmethod
    def _list_servers():
        """Return a list of registered OPC server ProgIDs on this machine."""
        try:
            return OpenOPC.enum_servers('localhost')
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_connection(self):
        if self._client is None:
            raise RuntimeError(
                'Not connected. Call connect() or use as a context manager.'
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    parser = argparse.ArgumentParser(
        description='OPC-DA controller for OLGA simulations.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  python opc_controller.py --status\n'
            '  python opc_controller.py --list-items "*PRESSURE*"\n'
            '  python opc_controller.py --read OLGA.PT1.PRESSURE\n'
            '  python opc_controller.py --write OLGA.PT1.SETPOINT 100.0\n'
            '  python opc_controller.py --monitor OLGA.PT1.PRESSURE --interval 2 --duration 60\n'
            '  python opc_controller.py --pause\n'
            '  python opc_controller.py --resume\n'
            '  python opc_controller.py --snapshot save MY_STATE\n'
            '  python opc_controller.py --snapshot load MY_STATE\n'
        ),
    )
    parser.add_argument(
        '--server', default=OLGA_OPC_SERVER,
        help='OPC server ProgID (default: %(default)s)',
    )
    parser.add_argument('--status', action='store_true',
                        help='Check OPC server availability')
    parser.add_argument('--connect', action='store_true',
                        help='Test connection to OPC server')
    parser.add_argument('--list-items', metavar='PATTERN', nargs='?',
                        const='*', help='List OPC items (default pattern: *)')
    parser.add_argument('--read', metavar='ITEM',
                        help='Read a single OPC item')
    parser.add_argument('--write', nargs=2, metavar=('ITEM', 'VALUE'),
                        help='Write VALUE to ITEM')
    parser.add_argument('--monitor', metavar='ITEM',
                        help='Monitor an OPC item')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Monitor poll interval in seconds (default: 1.0)')
    parser.add_argument('--duration', type=float, default=None,
                        help='Monitor duration in seconds (default: unlimited)')
    parser.add_argument('--pause', action='store_true',
                        help='Pause the simulation')
    parser.add_argument('--resume', action='store_true',
                        help='Resume the simulation')
    parser.add_argument('--snapshot', nargs=2, metavar=('ACTION', 'NAME'),
                        help='save or load a snapshot: --snapshot save NAME')
    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    # --status does not require a connection
    if args.status:
        info = OpcController.status()
        if info.get('error'):
            print('Error: ' + info['error'])
            sys.exit(1)
        if info['available']:
            print('OPC servers found:')
            for s in info['servers']:
                marker = ' <-- OLGA' if s == OLGA_OPC_SERVER else ''
                print('  ' + s + marker)
        else:
            print(
                'No OPC servers found. Ensure OLGA is running in server '
                'mode (SERVEROPTIONS in genkey) and that OlgaOpc-2022.1.0.exe '
                'is running.'
            )
        sys.exit(0)

    # All other commands need OPC available
    if not OPC_AVAILABLE:
        print('Error: OpenOPC is not installed. Run: pip install OpenOPC-Python3x')
        sys.exit(2)

    try:
        opc = OpcController(server_name=args.server)

        if args.connect:
            opc.connect()
            print('Connected to: ' + args.server)
            opc.disconnect()
            sys.exit(0)

        if args.list_items is not None:
            with opc:
                items = opc.list_items(args.list_items)
            for item in items:
                print(item)
            sys.exit(0)

        if args.read is not None:
            with opc:
                value, quality, timestamp = opc.read(args.read)
            print('{} = {} [{}] @ {}'.format(args.read, value, quality, timestamp))
            sys.exit(0)

        if args.write is not None:
            item, raw_value = args.write
            # Attempt numeric conversion; fall back to string
            try:
                value = float(raw_value)
                if value == int(value):
                    value = int(value)
            except ValueError:
                value = raw_value
            with opc:
                opc.write(item, value)
            print('Written: {} = {}'.format(item, value))
            sys.exit(0)

        if args.monitor is not None:
            with opc:
                opc.monitor(
                    args.monitor,
                    interval=args.interval,
                    duration=args.duration,
                )
            sys.exit(0)

        if args.pause:
            with opc:
                opc.pause()
            print('Simulation paused.')
            sys.exit(0)

        if args.resume:
            with opc:
                opc.resume()
            print('Simulation resumed.')
            sys.exit(0)

        if args.snapshot is not None:
            action, name = args.snapshot
            action = action.lower()
            if action not in ('save', 'load'):
                print('Error: --snapshot action must be "save" or "load".')
                sys.exit(2)
            with opc:
                if action == 'save':
                    opc.save_snapshot(name)
                    print('Snapshot saved: ' + name)
                else:
                    opc.load_snapshot(name)
                    print('Snapshot loaded: ' + name)
            sys.exit(0)

        parser.print_help()
        sys.exit(2)

    except ImportError as exc:
        print('Error: ' + str(exc))
        sys.exit(2)
    except (ConnectionError, PermissionError) as exc:
        print('Error: ' + str(exc))
        sys.exit(1)
    except RuntimeError as exc:
        print('Error: ' + str(exc))
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == '__main__':
    main()
