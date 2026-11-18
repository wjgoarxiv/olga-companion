from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from olga_companion.case_transaction_store import TransactionStoreError, load_transaction
from olga_companion.case_transactions import case_spec_hash, plan_case_edits
from case_spec_v2_support import PVT_TABLE_TEXT, with_v2_inputs


def _spec() -> dict:
    return with_v2_inputs({
        "version": "1",
        "nodes": [
            {"label": "SOURCE", "kind": "source", "pressure_pa": 2_000_000.0},
            {"label": "SINK", "kind": "sink", "pressure_pa": 1_000_000.0},
        ],
        "flowpaths": [{
            "label": "MAIN", "from": "SOURCE", "to": "SINK",
            "pipes": [{
                "label": "PIPE", "centerline_m": [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]],
                "diameter_m": 0.1, "sections": 2,
            }],
        }],
        "pvt_reference": "fluid.tab",
        "integration": {"end_time_s": 3600.0},
        "outputs": ["PT"],
    })


def test_durable_lookup_rejects_record_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given an otherwise valid durable record tampered to name an outside artifact.
    journal = tmp_path / "journal"
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(journal))
    (tmp_path / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    spec = _spec()
    result = plan_case_edits(
        spec, [{"op": "set_integration", "end_time_s": 7200.0}],
        expected_hash=case_spec_hash(spec), workspace_root=tmp_path,
    )
    outside = tmp_path / "outside.genkey"
    outside.write_bytes(b"attacker-controlled\n")
    record_path = journal / result.transaction_id / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["compiled_name"] = "../../outside.genkey"
    record["compiled_hash"] = hashlib.sha256(outside.read_bytes()).hexdigest()
    record_path.write_text(json.dumps(record), encoding="utf-8")

    # When publish lookup re-validates the private record.
    with pytest.raises(TransactionStoreError, match="malformed"):
        load_transaction(result.transaction_id)

    # Then no path-bearing record can escape its immutable transaction directory.
    assert outside.read_bytes() == b"attacker-controlled\n"
