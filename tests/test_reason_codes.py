"""N7: every system-status reason and run-failure code the server sends has words in the
frontend catalogue (en and ko), so the Korean screen never falls back to English text."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from olga_companion import run_receipt_status
from olga_companion.sidecar import _all_capabilities

I18N = Path(__file__).resolve().parents[1] / "frontend" / "src" / "i18n"


def _keys(locale: str) -> set[str]:
    return set(re.findall(r"^\s*'([^']+)':", (I18N / f"{locale}.ts").read_text(encoding="utf-8"), re.MULTILINE))


def test_every_capability_reason_has_a_code_with_words_in_both_languages() -> None:
    en, ko = _keys("en"), _keys("ko")
    for name, cap in _all_capabilities().items():
        if not isinstance(cap, dict):
            continue
        code = cap.get("reason_code")
        assert isinstance(code, str) and code, name
        assert f"env.reason.{code}" in en, name
        assert f"env.reason.{code}" in ko, name


def test_every_run_failure_code_has_words_in_both_languages() -> None:
    source = "\n".join(
        (Path(__file__).resolve().parents[1] / "src" / "olga_companion" / name).read_text(encoding="utf-8")
        for name in ("run_outputs.py", "run_dispatch.py", "run_receipt_status.py")
    )
    codes = set(re.findall(r'"code": "([a-z_]+)"', source))
    assert len(codes) >= 9
    en, ko = _keys("en"), _keys("ko")
    for code in codes:
        assert f"run.failure.{code}.title" in en and f"run.failure.{code}.title" in ko, code


def test_the_two_interrupted_stops_say_which_they_are() -> None:
    assert run_receipt_status._INTERRUPTED_FAILURE["variant"] == "app_closed"
    assert run_receipt_status._BROKER_GONE_FAILURE["variant"] == "helper_gone"


_CAPABILITY_SOURCES = ("genkey_static.py", "fluids.py", "run_queries.py", "results.py", "publication_plot.py", "opc.py", "diagnostics.py")


def _strings(node: ast.AST) -> set[str]:
    return {item.value for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str)}


def _source_reason_codes() -> set[str]:
    """Every code the capability builders can send, read from their source: a "reason_code"
    dict value, a value assigned to a name ending in "code", and the code of _fixture_smoke."""
    root = Path(__file__).resolve().parents[1] / "src" / "olga_companion"
    codes: set[str] = set()
    for name in _CAPABILITY_SOURCES:
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "reason_code" and value is not None:
                        codes |= _strings(value)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    names = target.elts if isinstance(target, ast.Tuple) else [target]
                    for index, item in enumerate(names):
                        if isinstance(item, ast.Name) and item.id.endswith("code"):
                            value = node.value.elts[index] if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple) else node.value
                            codes |= _strings(value)
            elif isinstance(node, ast.FunctionDef) and node.name == "_fixture_smoke":
                for ret in ast.walk(node):
                    if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Tuple):
                        codes |= _strings(ret.value.elts[-1])
    return {code for code in codes if re.fullmatch(r"[a-z]+(?:_[a-z]+)+", code)}


def test_every_code_in_the_source_has_words_in_both_languages() -> None:
    codes = _source_reason_codes()
    assert {"olga_unsupported_native", "broker_unavailable", "multiflash_needs_windows", "renderer_failed",
            "result_parser_failed", "diagnostics_missing", "opc_gated"} <= codes
    en, ko = _keys("en"), _keys("ko")
    missing = sorted(code for code in codes if f"env.reason.{code}" not in en or f"env.reason.{code}" not in ko)
    assert missing == []
