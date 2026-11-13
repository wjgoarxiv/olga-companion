"""T9d RED: the folder branch must use the modern picker dialog."""
from __future__ import annotations

from olga_companion import native_dialogs
from olga_companion.native_dialog_powershell import ENCODED_DIALOG_SCRIPT

COMMAND_LINE_LIMIT = 32767


def _folder_branch() -> str:
    script = native_dialogs.POWERSHELL_DIALOG_SCRIPT
    start = script.index("if ($kind -eq 'folder')")
    end = script.index("} elseif ($kind -eq 'case-open')")
    return script[start:end]


def test_folder_branch_uses_modern_common_item_dialog() -> None:
    branch = _folder_branch()
    assert "IFileOpenDialog" in branch
    assert "FOS_PICKFOLDERS" in branch


def test_folder_com_interop_declares_full_vtable_order() -> None:
    import re

    script = native_dialogs.POWERSHELL_DIALOG_SCRIPT
    interface = re.search(
        r"interface IFileOpenDialog \{(.*?)\n  \}", script, re.DOTALL
    )
    assert interface is not None
    methods = re.findall(r"\b(?:void|int|string)\s+(\w+)\s*\(", interface.group(1))
    assert methods == [
        "Show",
        "SetFileTypes",
        "SetFileTypeIndex",
        "GetFileTypeIndex",
        "Advise",
        "Unadvise",
        "SetOptions",
        "GetOptions",
        "SetDefaultFolder",
        "SetFolder",
        "GetFolder",
        "GetCurrentSelection",
        "SetFileName",
        "GetFileName",
        "SetTitle",
        "SetOkButtonLabel",
        "SetFileNameLabel",
        "GetResult",
    ]


def test_legacy_tree_dialog_is_fallback_only() -> None:
    script = native_dialogs.POWERSHELL_DIALOG_SCRIPT
    assert script.count("FolderBrowserDialog") == 1
    branch = _folder_branch()
    fallback = branch.split("catch", 1)[1]
    assert "FolderBrowserDialog" in fallback
    assert "IFileOpenDialog" in branch.split("catch", 1)[0]


def test_folder_branch_keeps_output_contract_and_owner() -> None:
    branch = _folder_branch()
    assert "@{ status = 'selected'; path =" in branch
    assert "@{ status = 'cancelled' }" in branch
    assert "$owner.Handle" in branch


def test_encoded_dialog_command_fits_command_line_limit() -> None:
    assert len(ENCODED_DIALOG_SCRIPT) + 512 < COMMAND_LINE_LIMIT
