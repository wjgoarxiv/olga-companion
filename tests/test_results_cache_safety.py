from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from olga_companion import results


class _CoordinatedEvictionCache(OrderedDict):
    """Pause a cache hit until a concurrent capacity eviction occurs."""

    def __init__(self) -> None:
        super().__init__()
        self.coordinate_hit = False
        self.hit_read = Event()
        self.eviction_done = Event()

    def get(self, key, default=None):
        value = super().get(key, default)
        if self.coordinate_hit and value is not None:
            self.hit_read.set()
            self.eviction_done.wait(timeout=0.5)
        return value

    def popitem(self, last=True):
        item = super().popitem(last=last)
        self.eviction_done.set()
        return item


def test_load_result_does_not_raise_when_a_concurrent_miss_evicts_the_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a one-entry cache whose current hit pauses before its LRU promotion.
    cache = _CoordinatedEvictionCache()
    monkeypatch.setattr(results, "_LOAD_CACHE", cache)
    monkeypatch.setattr(results, "_LOAD_CACHE_CAP", 1)
    monkeypatch.setattr(results, "resolve_result", Path)
    monkeypatch.setattr(results, "file_sha256", lambda path: path.stem)
    monkeypatch.setattr(
        results,
        "_parse_index",
        lambda path: {"ok": True, "file_type": path.suffix.casefold().lstrip(".")},
    )
    results.load_result("current.tpl")
    cache.coordinate_hit = True

    # When another load misses and attempts the capacity eviction concurrently.
    with ThreadPoolExecutor(max_workers=2) as executor:
        hit = executor.submit(results.load_result, "current.tpl")
        assert cache.hit_read.wait(timeout=1.0)
        miss = executor.submit(results.load_result, "next.tpl")

        # Then the hit remains a normal cached response instead of raising KeyError.
        assert hit.result(timeout=2.0)["cached"] is True
        assert miss.result(timeout=2.0)["cached"] is False


def test_load_result_does_not_alias_byte_identical_tpl_and_ppl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given byte-identical files whose suffixes select different parser modes.
    tpl = tmp_path / "same.tpl"
    ppl = tmp_path / "same.ppl"
    tpl.write_bytes(b"identical-result-payload")
    ppl.write_bytes(tpl.read_bytes())
    parsed_suffixes: list[str] = []

    def parse_by_suffix(path: Path) -> dict[str, str | bool]:
        suffix = path.suffix.casefold().lstrip(".")
        parsed_suffixes.append(suffix)
        return {"ok": True, "file_type": suffix}

    monkeypatch.setattr(results, "_LOAD_CACHE", OrderedDict())
    monkeypatch.setattr(results, "resolve_result", Path)
    monkeypatch.setattr(results, "_parse_index", parse_by_suffix)

    # When each file is loaded once.
    tpl_result = results.load_result(str(tpl))
    ppl_result = results.load_result(str(ppl))

    # Then each suffix owns a separately parsed cache entry.
    assert (
        tpl_result["file_type"],
        tpl_result["cached"],
        ppl_result["file_type"],
        ppl_result["cached"],
        parsed_suffixes,
    ) == ("tpl", False, "ppl", False, ["tpl", "ppl"])
