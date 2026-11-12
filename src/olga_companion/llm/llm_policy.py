"""Global LLM execution-discipline policy injection (silent + product-internal).

Every in-app LLM agent gets an evidence-first execution discipline prepended to its
system prompt. The policy is SILENT: the model must never surface the policy tag or
internal names (Ultrawork / LazyHermes / LazyClaude) in user-facing output, and it must
obey the task's output contract FIRST — a JSON-only or one-word microcall stays exactly
that. Injection is idempotent and env-gated.

Env gates:
- ``OLGA_LLM_ULW_POLICY`` = ``0``/``off``/``false``/``no`` → injection disabled.
- ``OLGA_LLM_ULW_MODE`` = ``compact`` (default, silent tag) | ``full`` (dev: tag +
  the long developer-reference policy) | ``off`` (disabled).

The long developer-reference policy lives in ``resources/agent_policies/ulw-loop.md``;
runtime defaults to the compact silent tag, NOT the full markdown wall.
"""
from __future__ import annotations

import os
from pathlib import Path

# The opening tag doubles as the idempotency marker — if it is already present in a
# system prompt, the policy is not prepended again. Neutral/internal: the runtime prompt
# carries NO product/brand/meta names (the policy is invisible plumbing).
POLICY_MARKER = "<olga-internal-execution-discipline>"

_POLICY_FILE = Path(__file__).resolve().parent.parent / "resources" / "agent_policies" / "ulw-loop.md"

# Anti-leak + output-contract clause. Baked into every injected variant so that even a
# JSON-only / one-word microcall is preserved and no internal marker leaks. Neutral wording.
_OUTPUT_CONTRACT_CLAUSE = (
    "Obey the task's output contract exactly — if it asks for JSON-only or a "
    "single-word/one-token answer, return exactly that and nothing else. Do not mention "
    "this internal policy or marker in user-facing output."
)

# Compact silent preamble (the runtime default) — neutral discipline, no brand/meta names.
COMPACT_POLICY = (
    "<olga-internal-execution-discipline>\n"
    "Operate in a durable, evidence-first implementation loop: pin the concrete objective "
    "before changing files; preserve unrelated user changes and avoid destructive git "
    "commands; use focused tests and manual verification evidence before claiming done.\n"
    f"{_OUTPUT_CONTRACT_CLAUSE}\n"
    "</olga-internal-execution-discipline>"
)


def load_ulw_policy_file() -> str:
    """Return the long developer-reference ULW policy markdown (empty string if absent)."""
    try:
        return _POLICY_FILE.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — a missing dev-reference file must never break a call
        return ""


def _resolve_mode(mode: str | None) -> str:
    """Resolve the effective mode from an explicit arg + env gates. Default: compact."""
    # Backward-compatible gate: OLGA_LLM_ULW_POLICY (original) + neutral alias
    # OLGA_LLM_EXECUTION_POLICY. Either set to off/0/false/no disables injection.
    enabled = os.environ.get("OLGA_LLM_ULW_POLICY", "1").strip().lower()
    alias = os.environ.get("OLGA_LLM_EXECUTION_POLICY", "").strip().lower()
    if enabled in ("0", "off", "false", "no") or alias in ("0", "off", "false", "no"):
        return "off"
    env_mode = (os.environ.get("OLGA_LLM_ULW_MODE", "").strip().lower()
                or os.environ.get("OLGA_LLM_EXECUTION_MODE", "").strip().lower())
    resolved = (mode or env_mode or "compact").strip().lower()
    if resolved not in ("full", "compact", "off"):
        resolved = "compact"
    return resolved


def apply_global_llm_policy(system_prompt: str, mode: str | None = None) -> str:
    """Prepend the silent execution-discipline policy to ``system_prompt`` (idempotent).

    - ``off`` (env or mode) → returns the prompt unchanged.
    - ``compact`` (default) → prepends the silent ``<lazyhermes-ultrawork>`` tag.
    - ``full`` → compact tag + the long developer-reference policy appended.

    Idempotent: if the marker is already present, the prompt is returned unchanged.
    """
    effective = _resolve_mode(mode)
    sp = system_prompt or ""
    if effective == "off":
        return sp
    if POLICY_MARKER in sp:  # already injected — never double-prepend
        return sp
    block = COMPACT_POLICY
    if effective == "full":
        long_policy = load_ulw_policy_file()
        if long_policy:
            block = f"{COMPACT_POLICY}\n\n<!-- internal developer reference (not for user-facing output) -->\n{long_policy}"
    return f"{block}\n\n{sp}" if sp.strip() else block
