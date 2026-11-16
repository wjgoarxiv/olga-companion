from olga_companion import native_dialogs


def test_save_as_uses_suggested_extension_when_user_omits_it() -> None:
    # Given: a SaveFileDialog seeded from a typed export artifact.
    script = native_dialogs.POWERSHELL_DIALOG_SCRIPT

    # When: the native dialog configures its suggested filename.
    suggested_name_branch = next(line for line in script.splitlines() if "if ($suggested)" in line)

    # Then: Windows receives the source suffix as its automatic default extension.
    assert "$extension = [IO.Path]::GetExtension($suggested).TrimStart('.')" in suggested_name_branch
    assert "$dialog.DefaultExt = $extension" in suggested_name_branch
    assert "$dialog.Filter = \"$($extension.ToUpperInvariant()) files (*.$extension)|*.$extension\"" in suggested_name_branch
    assert "$dialog.AddExtension = $true" in suggested_name_branch
