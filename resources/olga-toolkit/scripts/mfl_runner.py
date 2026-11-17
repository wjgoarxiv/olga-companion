"""
mfl_runner.py -- Execute Multiflash to generate .tab PVT tables.

Auto-detects the Multiflash installation and runs .mfl command scripts
to produce .tab PVT table files for OLGA simulations.

Usage as a library:
    from mfl_runner import MflRunner
    r = MflRunner('Case1.mfl')
    result = r.run(timeout=300)
    print(result['status'], result['output_tab_path'])

Standalone usage:
    python mfl_runner.py --status
    python mfl_runner.py Case1.mfl [--timeout 300] [--mfcmd-path PATH]

Exit codes: 0=success, 1=domain error, 2=I/O error.
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Ensure mfl_parser is importable (same scripts/ directory)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# MflRunner
# ---------------------------------------------------------------------------

class MflRunner:
    """Execute Multiflash to generate .tab PVT tables.

    Auto-detects Multiflash installation at:
    - MULTIFLASH_HOME environment variable
    - C:\\Program Files\\Schlumberger\\OLGA*\\Tools\\Multiflash\\
    """

    # Known executable names to search for
    _CLI_NAMES = ["mfcmd.exe", "MFCmd.exe", "MFCMD.EXE"]
    _GUI_NAMES = ["MFBJ01.exe", "mfbj01.exe"]

    def __init__(self, mfl_path: str, mfcmd_path: str = None):
        """Initialize with .mfl path and optional path to mfcmd executable.

        Parameters
        ----------
        mfl_path : str
            Path to the .mfl input file.
        mfcmd_path : str, optional
            Explicit path to the mfcmd executable.
        """
        self._mfl_path = mfl_path
        self._mfcmd_path = mfcmd_path

        if self._mfcmd_path is None:
            self._mfcmd_path = self._find_mfcmd()

        self._mf_home = self._find_multiflash_home()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @staticmethod
    def find_multiflash() -> dict:
        """Auto-detect Multiflash installation. Returns status dict."""
        info = {
            "installed": False,
            "home": None,
            "mfcmd": None,
            "gui": None,
            "version": None,
        }

        home = MflRunner._find_multiflash_home_static()
        if not home:
            return info

        info["installed"] = True
        info["home"] = home

        # Look for CLI executable
        for name in MflRunner._CLI_NAMES:
            candidate = os.path.join(home, name)
            if os.path.isfile(candidate):
                info["mfcmd"] = candidate
                break

        # Look for GUI executable
        for name in MflRunner._GUI_NAMES:
            candidate = os.path.join(home, name)
            if os.path.isfile(candidate):
                info["gui"] = candidate
                break

        # Try to extract version from path
        for part in Path(home).parts:
            if "OLGA" in part.upper():
                info["version"] = part
                break

        return info

    @staticmethod
    def _find_multiflash_home_static() -> str:
        """Search well-known locations for Multiflash directory."""
        # 1. MULTIFLASH_HOME environment variable
        mf_home = os.environ.get("MULTIFLASH_HOME")
        if mf_home and os.path.isdir(mf_home):
            return mf_home

        # 2. Program Files / Schlumberger / OLGA* / Tools / Multiflash
        for pattern in [
            r"C:/Program Files/Schlumberger/OLGA*/Tools/Multiflash",
            r"C:/Program Files (x86)/Schlumberger/OLGA*/Tools/Multiflash",
        ]:
            matches = sorted(glob.glob(pattern))
            if matches:
                return matches[-1]  # prefer latest version

        # 3. SLB branded paths (newer installations)
        for pattern in [
            r"C:/Program Files/SLB/OLGA*/Tools/Multiflash",
        ]:
            matches = sorted(glob.glob(pattern))
            if matches:
                return matches[-1]

        return None

    def _find_multiflash_home(self) -> str:
        """Instance method wrapping static discovery."""
        return self._find_multiflash_home_static()

    def _find_mfcmd(self) -> str:
        """Search for the mfcmd command-line executable."""
        home = self._find_multiflash_home_static()
        if not home:
            return None

        # Check for CLI executable in Multiflash directory
        for name in self._CLI_NAMES:
            candidate = os.path.join(home, name)
            if os.path.isfile(candidate):
                return candidate

        # Check system PATH
        for name in self._CLI_NAMES:
            which = shutil.which(name)
            if which:
                return which

        return None

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self, timeout: int = 300) -> dict:
        """Execute Multiflash and generate .tab file.

        Parameters
        ----------
        timeout : int
            Maximum seconds to wait for Multiflash (default 300).

        Returns
        -------
        dict
            Keys: status, output_tab_path, stdout, stderr, exit_code,
            duration_seconds.
        """
        result = {
            "status": "error",
            "output_tab_path": None,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "duration_seconds": 0.0,
            "mfl_path": self._mfl_path,
        }

        # Validate .mfl file exists
        if not os.path.isfile(self._mfl_path):
            result["stderr"] = "File not found: %s" % self._mfl_path
            return result

        # Extract expected output .tab path from .mfl
        expected_tab = self._extract_tab_path()
        result["output_tab_path"] = expected_tab

        # Check for mfcmd
        if not self._mfcmd_path:
            # Check if GUI-only installation
            gui_path = self._find_gui()
            if gui_path:
                result["status"] = "gui_only"
                result["stderr"] = (
                    "Multiflash is installed but only the GUI (MFBJ01.exe) "
                    "was found.\n"
                    "The command-line tool (mfcmd.exe) is not available.\n"
                    "Please run the .mfl file manually in the Multiflash GUI:\n"
                    "  1. Open MFBJ01.exe at: %s\n"
                    "  2. File -> Run Script -> select %s\n"
                    "  3. The .tab file will be generated at: %s"
                    % (gui_path, self._mfl_path,
                       expected_tab or "(path in .mfl)")
                )
                return result

            result["stderr"] = (
                "Multiflash not found.\n"
                "Searched: MULTIFLASH_HOME env, "
                "C:\\Program Files\\Schlumberger\\OLGA*\\Tools\\Multiflash\\\n"
                "Install Multiflash or set MULTIFLASH_HOME, "
                "or pass --mfcmd-path."
            )
            return result

        # Execute: mfcmd < input.mfl
        # mfcmd reads commands from stdin
        start = time.monotonic()
        try:
            with open(self._mfl_path, "r", encoding="utf-8") as mfl_file:
                proc = subprocess.Popen(
                    [self._mfcmd_path],
                    stdin=mfl_file,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=os.path.dirname(os.path.abspath(self._mfl_path)),
                )
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate()
                    result["stdout"] = stdout or ""
                    result["stderr"] = (stderr or "") + (
                        "\n[mfl_runner] Timed out after %ds and was terminated."
                        % timeout
                    )
                    result["duration_seconds"] = round(
                        time.monotonic() - start, 2
                    )
                    result["status"] = "timeout"
                    return result

                exit_code = proc.returncode

        except FileNotFoundError:
            result["stderr"] = "mfcmd not found at: %s" % self._mfcmd_path
            return result
        except OSError as exc:
            result["stderr"] = "Failed to launch mfcmd: %s" % exc
            return result

        elapsed = round(time.monotonic() - start, 2)

        result["exit_code"] = exit_code
        result["stdout"] = stdout or ""
        result["stderr"] = stderr or ""
        result["duration_seconds"] = elapsed

        # Check if .tab was generated
        if expected_tab and os.path.isfile(expected_tab):
            result["status"] = "success"
        elif exit_code == 0:
            # mfcmd returned 0 but .tab not found at expected path --
            # search in working directory
            mfl_dir = os.path.dirname(os.path.abspath(self._mfl_path))
            tab_files = glob.glob(os.path.join(mfl_dir, "*.tab"))
            if tab_files:
                # Use the most recently modified .tab
                newest = max(tab_files, key=os.path.getmtime)
                result["output_tab_path"] = newest
                result["status"] = "success"
            else:
                result["status"] = "completed_no_tab"
                result["stderr"] += (
                    "\n[mfl_runner] mfcmd exited 0 but no .tab file found."
                )
        else:
            result["status"] = "failed"

        return result

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @staticmethod
    def status() -> dict:
        """Check if Multiflash is available. Returns status dict."""
        info = MflRunner.find_multiflash()
        info["ready"] = info.get("mfcmd") is not None
        return info

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_tab_path(self) -> str:
        """Read the .mfl and extract the output .tab path from the table command."""
        try:
            with open(self._mfl_path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            try:
                with open(self._mfl_path, "r", encoding="latin-1") as f:
                    text = f.read()
            except OSError:
                return None

        m = re.search(r'"([^"]+\.tab)"', text, re.IGNORECASE)
        return m.group(1) if m else None

    def _find_gui(self) -> str:
        """Look for the Multiflash GUI executable."""
        home = self._find_multiflash_home()
        if not home:
            return None
        for name in self._GUI_NAMES:
            candidate = os.path.join(home, name)
            if os.path.isfile(candidate):
                return candidate
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mfl_runner.py",
        description="Execute Multiflash to generate .tab PVT tables.",
    )
    p.add_argument("mfl", nargs="?", default=None,
                   help="Path to the .mfl input file")
    p.add_argument("--timeout", metavar="SECS", type=int, default=300,
                   help="Maximum seconds to wait (default: 300)")
    p.add_argument("--mfcmd-path", metavar="PATH", default=None,
                   help="Explicit path to mfcmd executable")
    p.add_argument("--status", action="store_true",
                   help="Print Multiflash status and exit")
    return p


def _print_status():
    """Print formatted Multiflash status."""
    info = MflRunner.status()
    sep = "=" * 30

    print("Multiflash Status")
    print(sep)

    if not info["installed"]:
        print("Status:    NOT FOUND")
        print("Searched:  MULTIFLASH_HOME env,")
        print("           C:\\Program Files\\Schlumberger\\OLGA*\\Tools\\Multiflash\\")
        print("           C:\\Program Files\\SLB\\OLGA*\\Tools\\Multiflash\\")
        return

    print("Installed: Yes")
    print("Home:      %s" % info["home"])

    if info.get("version"):
        print("Version:   %s" % info["version"])

    if info["mfcmd"]:
        print("CLI:       %s" % info["mfcmd"])
        print("Status:    Ready (CLI available)")
    elif info["gui"]:
        print("GUI:       %s" % info["gui"])
        print("CLI:       NOT FOUND (mfcmd.exe)")
        print("Status:    GUI only -- manual execution required")
    else:
        print("CLI:       NOT FOUND")
        print("GUI:       NOT FOUND")
        print("Status:    Directory found but no executables detected")


def main():
    ap = _build_parser()
    args = ap.parse_args()

    if args.status:
        _print_status()
        sys.exit(0)

    if not args.mfl:
        ap.error("the following arguments are required: mfl")

    if not os.path.isfile(args.mfl):
        print("Error: file not found: %s" % args.mfl, file=sys.stderr)
        sys.exit(2)

    print("[mfl_runner] Input:   %s" % args.mfl)
    print("[mfl_runner] Timeout: %ds" % args.timeout)

    runner = MflRunner(args.mfl, mfcmd_path=args.mfcmd_path)
    result = runner.run(timeout=args.timeout)

    status = result["status"]

    if status == "success":
        print("[mfl_runner] SUCCESS (%.1fs)" % result["duration_seconds"])
        print("[mfl_runner] Output:  %s" % result["output_tab_path"])
        if result["stdout"].strip():
            print()
            print(result["stdout"])
        sys.exit(0)

    elif status == "gui_only":
        print("[mfl_runner] GUI-only installation detected.",
              file=sys.stderr)
        print(result["stderr"], file=sys.stderr)
        sys.exit(1)

    elif status == "timeout":
        print("[mfl_runner] TIMEOUT after %ds" % args.timeout,
              file=sys.stderr)
        if result["stderr"].strip():
            print(result["stderr"], file=sys.stderr)
        sys.exit(1)

    elif status == "completed_no_tab":
        print("[mfl_runner] mfcmd completed but .tab file not found.",
              file=sys.stderr)
        if result["stdout"].strip():
            print(result["stdout"])
        if result["stderr"].strip():
            print(result["stderr"], file=sys.stderr)
        sys.exit(1)

    else:
        print("[mfl_runner] FAILED (exit code %s)" % result["exit_code"],
              file=sys.stderr)
        if result["stderr"].strip():
            print(result["stderr"], file=sys.stderr)
        if result["stdout"].strip():
            print(result["stdout"])
        sys.exit(1)


if __name__ == "__main__":
    main()
