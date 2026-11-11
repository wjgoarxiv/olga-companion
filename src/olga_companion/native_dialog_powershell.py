"""Fixed PowerShell programs and bounded child-process I/O for native dialogs."""
from __future__ import annotations

import base64
import json
import subprocess
from typing import Any

from .native_dialog_contracts import NativeDialogError

MAX_OUTPUT_BYTES = 16 * 1024

POWERSHELL_DIALOG_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$kind = [Environment]::GetEnvironmentVariable('OLGA_DIALOG_KIND')
$initial = [Environment]::GetEnvironmentVariable('OLGA_DIALOG_INITIAL')
$suggested = [Environment]::GetEnvironmentVariable('OLGA_DIALOG_SUGGESTED')
$result = $null; $owner = [System.Windows.Forms.Form]::new(); $owner.TopMost = $true; $owner.ShowInTaskbar = $false; $owner.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None; $owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen; $owner.Size = [System.Drawing.Size]::new(1, 1); $owner.Opacity = 0; $owner.Show(); $null = $owner.Activate(); try {
if ($kind -eq 'folder') {
  $dialog = [System.Windows.Forms.FolderBrowserDialog]::new()
  $dialog.Description = 'Choose OLGA workspace folder'
  if ($initial) { $dialog.SelectedPath = $initial }
  if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
    $result = @{ status = 'selected'; path = $dialog.SelectedPath }
  } else { $result = @{ status = 'cancelled' } }
} elseif ($kind -eq 'case-open') {
  $dialog = [System.Windows.Forms.OpenFileDialog]::new()
  $dialog.Title = 'Open OLGA case'
  $dialog.Filter = 'OLGA cases (*.genkey;*.tab)|*.genkey;*.tab'
  $dialog.CheckFileExists = $true
  $dialog.Multiselect = $false
  if ($initial) { $dialog.InitialDirectory = $initial }
  if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
    $result = @{ status = 'selected'; path = $dialog.FileName }
  } else { $result = @{ status = 'cancelled' } }
} elseif ($kind -eq 'save-as') {
  $dialog = [System.Windows.Forms.SaveFileDialog]::new()
  $dialog.Title = 'Save export as'
  $dialog.OverwritePrompt = $true
  if ($initial) { $dialog.InitialDirectory = $initial }
  if ($suggested) { $extension = [IO.Path]::GetExtension($suggested).TrimStart('.'); $dialog.FileName = $suggested; $dialog.DefaultExt = $extension; $dialog.Filter = "$($extension.ToUpperInvariant()) files (*.$extension)|*.$extension"; $dialog.AddExtension = $true }
  if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
    $result = @{ status = 'selected'; path = $dialog.FileName }
  } else { $result = @{ status = 'cancelled' } }
} else { throw 'Unsupported dialog kind.' } } finally { $owner.Close(); $owner.Dispose() }
[Console]::Out.Write(($result | ConvertTo-Json -Compress))
""".strip()

ENCODED_DIALOG_SCRIPT = base64.b64encode(
    POWERSHELL_DIALOG_SCRIPT.encode("utf-16le")
).decode("ascii")

POWERSHELL_REPLACE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$replacement = [Environment]::GetEnvironmentVariable('OLGA_REPLACE_SOURCE')
$destination = [Environment]::GetEnvironmentVariable('OLGA_REPLACE_DESTINATION')
$backup = [Environment]::GetEnvironmentVariable('OLGA_REPLACE_BACKUP')
if ([IO.File]::Exists($backup)) { throw 'Backup path already exists.' }
[IO.File]::Replace($replacement, $destination, $backup, $true)
[Console]::Out.Write('ok')
""".strip()

ENCODED_REPLACE_SCRIPT = base64.b64encode(
    POWERSHELL_REPLACE_SCRIPT.encode("utf-16le")
).decode("ascii")


def _wait_best_effort(process: Any, timeout: float) -> None:
    try:
        process.wait(timeout=timeout)
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - process is already gone
        return


def terminate_reap(process: Any) -> None:
    try:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        finally:
            _wait_best_effort(process, 1.0)
    except (OSError, ProcessLookupError):
        _wait_best_effort(process, 0.1)


def read_bounded(stream: Any) -> bytes:
    stream.flush()
    stream.seek(0)
    return stream.read(MAX_OUTPUT_BYTES + 1)


def parse_output(payload: bytes) -> dict[str, str]:
    if len(payload) > MAX_OUTPUT_BYTES:
        raise NativeDialogError("PowerShell dialog output was too large")
    try:
        text = payload.decode("utf-8-sig")
        decoder = json.JSONDecoder()
        value, end = decoder.raw_decode(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeDialogError("PowerShell dialog output was malformed") from exc
    if text[end:].strip() or not isinstance(value, dict):
        raise NativeDialogError("PowerShell dialog output was malformed")
    status = value.get("status")
    if status == "cancelled" and set(value) == {"status"}:
        return {"status": "cancelled"}
    if (
        status == "selected"
        and set(value) == {"status", "path"}
        and isinstance(value.get("path"), str)
    ):
        return {"status": "selected", "path": value["path"]}
    raise NativeDialogError("PowerShell dialog output was malformed")
