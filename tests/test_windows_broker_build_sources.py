from __future__ import annotations

from pathlib import Path

from olga_companion import windows_broker


def test_declared_source_set_covers_every_checked_in_broker_source() -> None:
    source_dir = Path(windows_broker.__file__).with_name("broker")

    assert windows_broker._source_paths() == tuple(
        source_dir / name for name in windows_broker.BROKER_SOURCE_NAMES
    )
    assert set(windows_broker._source_paths()) == set(
        source_dir.glob("OlgaExplorerBroker*.cs")
    )


def test_compiler_command_binds_every_checked_in_broker_source(tmp_path: Path) -> None:
    sources = (tmp_path / "Broker.cs", tmp_path / "Broker.Native.cs")
    for source in sources:
        source.write_text("internal static partial class Broker {}", encoding="utf-8")

    command = windows_broker._compiler_command(
        tmp_path / "csc.exe",
        tmp_path / "broker.exe",
        sources,
    )

    assert command[-2:] == [windows_broker._windows_path(source) for source in sources]


def test_broker_source_identity_binds_names_and_contents(tmp_path: Path) -> None:
    first = tmp_path / "Broker.cs"
    second = tmp_path / "Broker.Native.cs"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    original = windows_broker._source_sha256((first, second))
    second.write_text("changed", encoding="utf-8")

    assert windows_broker._source_sha256((first, second)) != original
    assert windows_broker._source_sha256((second, first)) != original
