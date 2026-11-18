"""Exceptions of the independent PVT engine."""

from __future__ import annotations


class PvtEngineError(ValueError):
    """Base class: every engine refusal is a ValueError with a user-readable message."""


class UnknownComponentError(PvtEngineError):
    pass


class UnsupportedModelError(PvtEngineError):
    pass


class UnsupportedStateError(PvtEngineError):
    """A state outside the temperature, pressure or composition window the engine supports."""


class GridPolicyError(PvtEngineError):
    """A grid reaches into a region the engine refuses to describe (for example dry ice)."""


class NonPhysicalValueError(PvtEngineError):
    """A computed property failed a physical check; the table is not written."""


class OverwriteError(PvtEngineError):
    """The destination, or its fill-report sidecar, already exists."""
