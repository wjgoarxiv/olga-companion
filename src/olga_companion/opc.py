from __future__ import annotations

import platform
from typing import Any

from .config import toolkit_dir
from .genkey_static import run_tool

OPC_SCRIPTS = {
    "opc_controller": "opc_controller.py",
}


class OpcGateClosedError(PermissionError):
    """Raised when an OPC operation is requested while the gate is closed."""


def _detect_dependencies() -> tuple[bool, str, dict[str, Any] | None]:
    script = toolkit_dir() / "scripts" / OPC_SCRIPTS["opc_controller"]
    if not script.exists():
        return False, "opc_controller.py is not available in the toolkit.", None
    command = run_tool("opc_controller", ["--status"], timeout_s=20, names=OPC_SCRIPTS)
    output = f"{command.stdout}\n{command.stderr}"
    # Exit codes are ambiguous here: missing OpenOPC exits 1, but an installed
    # host with no running server ALSO exits 0 ("No OPC servers found"), the
    # same code as success — so the printed text is the trustworthy signal.
    if "not installed" in output or "Error:" in output:
        detail = output.strip().splitlines()[0] if output.strip() else "OPC status probe failed"
        return False, detail, command.to_dict()
    if any(line.strip().startswith("OPC servers found:") for line in output.splitlines()):
        return True, "OPC servers detected by the status probe.", command.to_dict()
    return False, f"OPC status probe found no servers: {output.strip().splitlines()[0] if output.strip() else 'no output'}", command.to_dict()


def opc_gate_status() -> dict[str, Any]:
    on_windows = platform.system() == "Windows"
    deps_ok, deps_reason, probe = _detect_dependencies()
    conditions = {
        "opc_dependencies": {
            "satisfied": deps_ok,
            "reason": deps_reason,
        },
        "windows_dcom": {
            "satisfied": False,
            "reason": (
                "DCOM permissions must be verified on the Windows host running OLGA server mode."
                if on_windows
                else f"OPC-DA requires Windows DCOM; this host is {platform.system()}."
            ),
        },
        "olga_server_mode": {
            "satisfied": False,
            "reason": "No running OLGA server-mode simulation has been detected and verified.",
        },
        "read_write_separation": {
            "satisfied": False,
            "reason": "Read/write item separation has not been verified against a live OPC server.",
        },
        "explicit_write_approval": {
            "satisfied": False,
            "reason": "The per-request write approval + snapshot flow has not passed live QA.",
        },
    }
    enabled = all(condition["satisfied"] for condition in conditions.values())
    return {
        "enabled": enabled,
        "conditions": conditions,
        "probe": probe,
    }


def require_open_gate() -> dict[str, Any]:
    status = opc_gate_status()
    if not status["enabled"]:
        blockers = "; ".join(
            f"{name}: {condition['reason']}"
            for name, condition in status["conditions"].items()
            if not condition["satisfied"]
        )
        raise OpcGateClosedError(f"OPC live-control gate is closed — {blockers}")
    return status


def opc_capabilities() -> dict[str, Any]:
    status = opc_gate_status()
    unsatisfied = [name for name, condition in status["conditions"].items() if not condition["satisfied"]]
    return {
        "opc_live_control": {
            "enabled": status["enabled"],
            "reason": (
                "All OPC gate conditions verified."
                if status["enabled"]
                else f"Gated until verified: {', '.join(unsatisfied)}."
            ),
        },
    }
