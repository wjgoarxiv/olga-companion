from __future__ import annotations

from . import olga_runtime_commands as _commands
from . import olga_runtime_detection as _detection
from . import olga_runtime_paths as _paths
from . import olga_runtime_versions as _versions


# Keep this module as the stable import surface used by the runner and tests.
DEFAULT_OLGA_EXE_GLOBS = _paths.DEFAULT_OLGA_EXE_GLOBS
MAX_EVIDENCE_BYTES = _versions.MAX_EVIDENCE_BYTES
EVIDENCE_CLOCK_SKEW_TOLERANCE_SECONDS = _versions.EVIDENCE_CLOCK_SKEW_TOLERANCE_SECONDS

_PATH_VERSION = _versions.PATH_VERSION
_OUT_VERSION = _versions.OUT_VERSION
_OUT_INPUT = _versions.OUT_INPUT
_NORMAL_STOP = _versions.NORMAL_STOP
_RESULT_VERSION = _versions.RESULT_VERSION
_RESULT_INPUT = _versions.RESULT_INPUT
_RESULT_INPUT_MULTILINE = _versions.RESULT_INPUT_MULTILINE

executable_kind = _paths.executable_kind
_version = _versions.version
_path_version = _versions.path_version
_path_key = _paths.path_key
_executable_sha256 = _detection.executable_sha256
_candidate = _detection.candidate
_candidate_sort_key = _detection.candidate_sort_key
_public_candidate = _detection.public_candidate
_input_basename = _paths.input_basename
_read_bounded = _versions.read_bounded
_evidence_from = _versions.evidence_from
_case_evidence = _versions.case_evidence

detect_olga = _detection.detect_olga
build_command = _commands.build_command
build_display_command = _commands.build_display_command
