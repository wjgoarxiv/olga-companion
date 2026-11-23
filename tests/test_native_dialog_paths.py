from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import native_dialogs

pytest_plugins = ("native_dialogs_test_fixtures",)


def test_windows_local_path_conversion_preserves_unicode_and_spaces(
    tmp_path: Path,
) -> None:
    local = native_dialogs.windows_to_local(
        r"C:\사용자 파일\case.genkey", native_windows=False
    )
    assert local == Path("/mnt/c/사용자 파일/case.genkey")
    assert (
        native_dialogs.local_to_windows(local, native_windows=False)
        == r"C:\사용자 파일\case.genkey"
    )


@pytest.mark.parametrize(
    "value",
    [
        r"\\server\share\case.genkey",
        r"\\?\C:\case.genkey",
        r"relative\case.genkey",
        "C:\\bad\nname",
    ],
)
def test_windows_path_conversion_rejects_unsafe_forms(value: str) -> None:
    with pytest.raises(native_dialogs.NativeDialogError):
        native_dialogs.windows_to_local(value, native_windows=False)
    with pytest.raises(native_dialogs.NativeDialogError):
        native_dialogs.local_to_windows(value, native_windows=True)


def test_local_path_conversion_rejects_unsupported_wsl_path() -> None:
    with pytest.raises(native_dialogs.NativeDialogError, match="WSL|mounted|drive"):
        native_dialogs.local_to_windows(
            Path("/home/user/case.genkey"), native_windows=False
        )


@pytest.mark.parametrize(
    "value",
    [
        r"C:\safe\..\case.genkey",
        r"C:\safe\.\case.genkey",
        r"C:\safe\case.genkey:secret",
        r"C:\safe\CON",
        r"C:\safe\con.txt",
        r"C:\safe\PRN.dat",
        r"C:\safe\COM1.log",
        r"C:\safe\LPT9",
        "C:\\safe\\trailing.",
        "C:\\safe\\trailing ",
    ],
)
def test_windows_to_local_rejects_ambiguous_or_device_components(value: str) -> None:
    with pytest.raises(native_dialogs.NativeDialogError):
        native_dialogs.windows_to_local(value, native_windows=False)
    with pytest.raises(native_dialogs.NativeDialogError):
        native_dialogs.windows_to_local(value, native_windows=True)
    with pytest.raises(native_dialogs.NativeDialogError):
        native_dialogs.local_to_windows(value, native_windows=True)


@pytest.mark.parametrize(
    "value",
    [
        "/mnt/c/safe/../case.genkey",
        "/mnt/c/safe/./case.genkey",
        "/mnt/c/safe/case.genkey:secret",
        "/mnt/c/safe/NUL.txt",
        "/mnt/c/safe/AUX",
        "/mnt/c/safe/COM9.dat",
        "/mnt/c/safe/LPT1",
        "/mnt/c/safe/trailing.",
        "/mnt/c/safe/trailing ",
    ],
)
def test_local_to_windows_rejects_ambiguous_or_device_components(value: str) -> None:
    with pytest.raises(native_dialogs.NativeDialogError):
        native_dialogs.local_to_windows(value, native_windows=False)


def test_windows_path_conversion_preserves_drive_root_and_mixed_normal_separators() -> (
    None
):
    assert native_dialogs.windows_to_local(
        "C:/Unicode 폴더\\case.genkey", native_windows=False
    ) == Path("/mnt/c/Unicode 폴더/case.genkey")
    assert native_dialogs.windows_to_local("D:\\", native_windows=False) == Path(
        "/mnt/d"
    )
    assert native_dialogs.local_to_windows("/mnt/d", native_windows=False) == "D:\\"
    assert native_dialogs.local_to_windows(
        "C:/Unicode 폴더\\case.genkey", native_windows=True
    ) == ("C:\\Unicode 폴더\\case.genkey")
