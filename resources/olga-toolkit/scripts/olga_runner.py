"""
olga_runner.py — OLGA simulation runner using opi.exe.

Usage:
    python olga_runner.py <file.genkey> [--output-dir DIR] [--timeout SECS]
                          [--no-validate] [--opi-path PATH]

Exit code matches OLGA exit code (0 = success).
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# OlgaRunner
# ---------------------------------------------------------------------------

class OlgaRunner:
    """Locate opi.exe, validate genkey files, and run OLGA simulations."""

    def __init__(self, opi_path: str = None):
        if opi_path is not None:
            self.opi_path = opi_path if Path(opi_path).is_file() else None
        else:
            self.opi_path = self.find_opi()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def find_opi(self) -> str | None:
        """Scan well-known locations for opi.exe and return the first found path."""
        # 1. OLGA_HOME environment variable
        olga_home = os.environ.get("OLGA_HOME")
        if olga_home:
            candidate = Path(olga_home) / "bin" / "opi.exe"
            if candidate.is_file():
                return str(candidate)

        # 2. Program Files (64-bit)
        for pattern in [
            r"C:/Program Files/Schlumberger/OLGA*/bin/opi.exe",
            r"C:/Program Files (x86)/Schlumberger/OLGA*/bin/opi.exe",
        ]:
            matches = sorted(glob.glob(pattern))
            if matches:
                return matches[-1]  # prefer highest (latest) version

        # 3. System PATH
        which = shutil.which("opi.exe")
        if which:
            return which

        return None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_before_run(self, genkey_path: str) -> tuple[bool, list]:
        """Pre-flight checks before launching a simulation.

        Returns (ok, errors) where errors is a list of human-readable strings.
        """
        errors = []
        p = Path(genkey_path)

        # File existence
        if not p.exists():
            errors.append(f"File not found: {genkey_path}")
            return False, errors

        # Extension check
        if p.suffix.lower() != ".genkey":
            errors.append(
                f"Expected a .genkey file, got: {p.suffix!r} ({genkey_path})"
            )

        # genkey_validator
        try:
            _scripts_dir = str(Path(__file__).parent)
            if _scripts_dir not in sys.path:
                sys.path.insert(0, _scripts_dir)

            from genkey_parser import GenkeyParser
            from genkey_validator import GenkeyValidator

            parser = GenkeyParser(str(p))
            validator = GenkeyValidator(parser)
            findings = validator.validate()
            validator_errors = [
                f"[{f['rule_id']}] {f['message']}"
                for f in findings
                if f.get("severity") == "ERROR"
            ]
            errors.extend(validator_errors)
        except ImportError as exc:
            errors.append(f"genkey_validator unavailable (import error): {exc}")
        except Exception as exc:
            errors.append(f"genkey_validator raised an exception: {exc}")

        # opi.exe availability
        if not self.opi_path:
            errors.append(
                "opi.exe not found. Set OLGA_HOME, install OLGA, or pass --opi-path."
            )

        if errors:
            return False, errors
        return True, []

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        genkey_path: str,
        output_dir: str = None,
        timeout: int = 3600,
        validate: bool = True,
    ) -> dict:
        """Launch opi.exe on the given genkey file and return a result dict."""
        result = {
            "success": False,
            "exit_code": None,
            "genkey_path": genkey_path,
            "output_dir": output_dir,
            "stdout": "",
            "stderr": "",
            "duration_seconds": 0.0,
            "output_files": [],
            "validation_errors": [],
        }

        # Pre-flight
        if validate:
            ok, val_errors = self.validate_before_run(genkey_path)
            if not ok:
                result["validation_errors"] = val_errors
                return result

        # opi.exe must be available to proceed
        if not self.opi_path:
            result["validation_errors"] = [
                "opi.exe not found. Set OLGA_HOME, install OLGA, or pass --opi-path."
            ]
            return result

        # Build command
        cmd = [self.opi_path, "-f", genkey_path]
        if output_dir:
            cmd += ["-o", output_dir]

        # Create output directory if specified
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Execute
        stdout_lines = []
        stderr_lines = []
        start = time.monotonic()

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            # Read stdout/stderr in real-time using communicate with timeout
            try:
                stdout_data, stderr_data = proc.communicate(timeout=timeout)
                stdout_lines = stdout_data.splitlines(keepends=True)
                stderr_lines = stderr_data.splitlines(keepends=True)
                for line in stdout_lines:
                    print(line, end="", flush=True)
                for line in stderr_lines:
                    print(line, end="", file=sys.stderr, flush=True)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_data, stderr_data = proc.communicate()
                stdout_lines = stdout_data.splitlines(keepends=True) if stdout_data else []
                stderr_lines = stderr_data.splitlines(keepends=True) if stderr_data else []
                stderr_lines.append(
                    f"\n[olga_runner] Simulation timed out after {timeout}s and was terminated.\n"
                )
                result["stderr"] = "".join(stderr_lines)
                result["stdout"] = "".join(stdout_lines)
                result["duration_seconds"] = round(time.monotonic() - start, 2)
                return result

            exit_code = proc.returncode

        except FileNotFoundError:
            result["validation_errors"] = [
                f"opi.exe not found at path: {self.opi_path}"
            ]
            return result
        except OSError as exc:
            result["validation_errors"] = [f"Failed to launch opi.exe: {exc}"]
            return result

        elapsed = round(time.monotonic() - start, 2)

        result["exit_code"] = exit_code
        result["success"] = exit_code == 0
        result["stdout"] = "".join(stdout_lines)
        result["stderr"] = "".join(stderr_lines)
        result["duration_seconds"] = elapsed

        # Collect output files
        scan_dir = output_dir or str(Path(genkey_path).parent)
        result["output_files"] = self.list_output_files(scan_dir)

        return result

    # ------------------------------------------------------------------
    # Output file listing
    # ------------------------------------------------------------------

    def list_output_files(self, output_dir: str) -> list[dict]:
        """Return metadata for OLGA output files (.tpl, .ppl, .rsw, .out)."""
        _type_map = {
            ".tpl": "trend",
            ".ppl": "profile",
            ".rsw": "restart",
            ".out": "log",
        }

        files = []
        base = Path(output_dir)
        if not base.is_dir():
            return files

        for ext, file_type in _type_map.items():
            for fp in sorted(base.glob(f"*{ext}")):
                try:
                    size_kb = round(fp.stat().st_size / 1024, 2)
                except OSError:
                    size_kb = 0.0
                files.append({
                    "name": fp.name,
                    "path": str(fp),
                    "size_kb": size_kb,
                    "type": file_type,
                })

        return files

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> str:
        """Return a human-readable status block."""
        sep = "=" * 18

        if self.opi_path:
            # Try to extract version from path (e.g. "OLGA 2024.1")
            version = "(unknown)"
            parts = Path(self.opi_path).parts
            for part in parts:
                upper = part.upper()
                if "OLGA" in upper:
                    version = part
                    break

            lines = [
                "OLGA Runner Status",
                sep,
                f"opi.exe: {self.opi_path}",
                f"Version: {version}",
                "Status:  Ready",
            ]
        else:
            lines = [
                "OLGA Runner Status",
                sep,
                "opi.exe: NOT FOUND",
                "Searched: OLGA_HOME, Program Files, PATH",
                "Status:  OLGA not installed or not in expected location",
            ]

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="olga_runner.py",
        description="Run an OLGA simulation via opi.exe.",
    )
    p.add_argument("genkey", nargs="?", default=None,
                   help="Path to the .genkey input file")
    p.add_argument("--output-dir", metavar="DIR", default=None,
                   help="Directory for simulation output files")
    p.add_argument("--timeout", metavar="SECS", type=int, default=3600,
                   help="Maximum wall-clock seconds to wait (default: 3600)")
    p.add_argument("--no-validate", action="store_true",
                   help="Skip pre-flight validation")
    p.add_argument("--opi-path", metavar="PATH", default=None,
                   help="Explicit path to opi.exe")
    p.add_argument("--status", action="store_true",
                   help="Print runner status and exit")
    return p


def main():
    parser = _build_parser()
    args = parser.parse_args()

    runner = OlgaRunner(opi_path=args.opi_path)

    if args.status:
        print(runner.status())
        sys.exit(0)

    if not args.genkey:
        parser.error("the following arguments are required: genkey")

    print(f"[olga_runner] Starting simulation: {args.genkey}")
    if args.output_dir:
        print(f"[olga_runner] Output directory:   {args.output_dir}")
    print(f"[olga_runner] Timeout:            {args.timeout}s")
    print(f"[olga_runner] Validation:         {'disabled' if args.no_validate else 'enabled'}")
    print()

    result = runner.run(
        genkey_path=args.genkey,
        output_dir=args.output_dir,
        timeout=args.timeout,
        validate=not args.no_validate,
    )

    # Validation failure
    if result["validation_errors"]:
        print("\n[olga_runner] Pre-flight validation FAILED:", file=sys.stderr)
        for err in result["validation_errors"]:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    # Summary
    status_str = "SUCCESS" if result["success"] else "FAILED"
    print(f"\n[olga_runner] Simulation {status_str} "
          f"(exit code {result['exit_code']}, "
          f"{result['duration_seconds']}s)")

    if result["output_files"]:
        print(f"[olga_runner] Output files ({len(result['output_files'])}):")
        for f in result["output_files"]:
            print(f"  [{f['type']:7s}] {f['name']}  ({f['size_kb']} KB)")

    sys.exit(result["exit_code"] if result["exit_code"] is not None else 1)


if __name__ == "__main__":
    main()
