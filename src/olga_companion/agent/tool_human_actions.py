"""Authenticated direct human actions intentionally absent from model tools."""

from typing import Final

DIRECT_HUMAN_ACTIONS: Final = {
    "run_emergency_stop": {
        "actor": "human",
        "approval_required": False,
        "authenticated": True,
        "immediate": True,
    }
}
