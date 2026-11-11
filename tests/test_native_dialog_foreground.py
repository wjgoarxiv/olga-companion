from olga_companion import native_dialogs


def test_common_dialogs_have_a_topmost_owner_when_browser_has_focus() -> None:
    # Given the fixed PowerShell program used for every native dialog request.
    script = native_dialogs.POWERSHELL_DIALOG_SCRIPT

    # When its modal ownership contract is inspected.
    owner_show_calls = script.count("$dialog.ShowDialog($owner)")

    # Then every common dialog is owned by one visible topmost host that is disposed.
    assert "$owner = [System.Windows.Forms.Form]::new()" in script
    assert "$owner.TopMost = $true" in script
    assert "$owner.ShowInTaskbar = $false" in script
    assert "$owner.Show()" in script
    assert owner_show_calls == 3
    assert "finally { $owner.Close(); $owner.Dispose() }" in script
