# OLGA Companion — Native Packaging Runbook (M7)

The product targets **Windows** because OLGA is Windows software. Run native
installer builds from Windows even when source editing and frontend QA happen
through WSL.

## Host status

Feasibility probe results on the development host:

- `cargo 1.95.0` / `rustc 1.95.0` — present.
- Tauri CLI is a repository dev dependency.
- `webkit2gtk-4.1` / `webkit2gtk-4.0` — absent (`pkg-config` misses; zero `libwebkit` dpkg packages), so even a Linux-target `tauri build` cannot compile here.
- A Windows `.msi`/`.nsis` target requires the Windows MSVC toolchain + WebView2, i.e. a Windows host.

The checked-in `src-tauri` crate, capability, icons, and external-binary
configuration are host-independent. Installer creation remains a Windows-only
gate.

## Prerequisites (Windows host)

1. Rust (stable, MSVC toolchain): `winget install Rustlang.Rustup`, then `rustup default stable-msvc`.
2. Microsoft Visual Studio Build Tools (C++ workload).
3. WebView2 Runtime (preinstalled on Windows 11; otherwise the Evergreen installer).
4. Node.js ≥ 22.12 (Vite 8/rolldown floor; the repo gates also need native type stripping) and Python ≥ 3.11.
5. Repository-local Tauri CLI (`npm ci` installs it).

## Step 0 — Verify the checked-in native host

The Tauri host is versioned under `src-tauri/`. It starts the bundled sidecar
from Rust, redirects mutable state to Tauri's per-user app-local-data directory,
and points `OLGA_TOOLKIT_DIR` at the bundled toolkit resource. The WebView has
only `core:default`; it cannot invoke arbitrary shell commands. The host owns
the child-process lifecycle through `tauri-plugin-shell`, so the sidecar starts
with the app and is terminated when the desktop process exits.

```powershell
npm ci
cargo fmt --manifest-path src-tauri\Cargo.toml -- --check
cargo clippy --manifest-path src-tauri\Cargo.toml --all-targets -- -D warnings
```

## Step 1 — Package the Python sidecar

The sidecar (`src/olga_companion`) ships as a Tauri external binary built with PyInstaller:

```powershell
python -m pip install pyinstaller ".[results]"
uv run --isolated --no-dev --extra results --with pyinstaller pyinstaller `
  --onefile --name olga-companion-sidecar `
  --paths src `
  --collect-submodules olga_companion `
  --exclude-module olga_companion.pvt_engine `
  --exclude-module olga_companion.native_tab `
  --collect-data olga_companion `
  --collect-all pyfas `
  --collect-all easydict `
  --hidden-import win32com.client `
  --add-data "src\olga_companion\broker\OlgaExplorerBroker.cs;olga_companion\broker" `
  --add-data "src\olga_companion\broker\OlgaExplorerBroker.Native.cs;olga_companion\broker" `
  --add-data "src\olga_companion\broker\OlgaExplorerBroker.Protocol.cs;olga_companion\broker" `
  scripts\package_sidecar.py
```

Copy the result to the Tauri external-binary location with the target triple suffix Tauri requires:

```powershell
mkdir src-tauri\binaries
copy dist\olga-companion-sidecar.exe src-tauri\binaries\olga-companion-sidecar-x86_64-pc-windows-msvc.exe
```

**Independent table engine (local PVT Verify builds only).** `olga_companion.pvt_engine` is a
pure-Python package (standard library only, no runtime data files, no JRE, no Java). The folder
carries an MIT `LICENSE` notice; that notice is not engine data. Its runtime is the
sidecar's own Python interpreter: under 100 KB of source, and no separate runtime is bundled.
`olga_companion.native_tab` is its adapter. `--collect-submodules olga_companion` alone would put
both in a bundle, so the release command above excludes them with the two `--exclude-module` lines,
and a release sidecar contains neither the engine nor its adapter. Checked against PyInstaller 6.21:
`--collect-submodules` only appends the package's modules to the hidden imports, and an exclusion
beats them, so excluding a package excludes its submodules as well. Each submodule then shows one
`Hidden import ... not found` line in the build log; that is expected and harmless. `--collect-data`
skips `.py` files by default, so it does not bring the sources back. It can still copy the MIT
`LICENSE` notice, because that hook copies non-Python files from the package tree. The release
command above does not change: the two `--exclude-module` lines still keep the engine and its
adapter out of a release sidecar.

Whether the generator is *on* is a separate runtime switch. The tool, its prompt text and its plan
step exist only when the sidecar starts with `OLGA_COMPANION_NATIVE_TAB=1`; a release sidecar never
sets it. The PVT Verify recipe is the release command with two changes. Delete both
`--exclude-module` lines, so the engine is collected, and add
`--runtime-hook "%REPO%\scripts\pvt_native_tab_hook.py"`, which writes the variable before any app
module loads. Nothing else in the PVT command differs. For a dev server, start it with
`OLGA_COMPANION_NATIVE_TAB=1`. The engine and this switch are never released (owner decision
2026-10-31); tests pin that the release command carries the exclusions, that nothing in the host,
the Tauri configuration or the entry point sets the variable, and that the local PVT build script
keeps the engine.

**Why `--collect-all pyfas` is mandatory, not optional.** When frozen, the sidecar re-enters
itself to run toolkit scripts (`genkey_tool_runner.tool_command()` returns
`[sys.executable, "--tool-script", …]`), so toolkit scripts resolve their imports from the
bundle. `pyfas` is imported only by *toolkit scripts*, which PyInstaller treats as data files
rather than imports — its static analysis never sees them, and `--collect-submodules
olga_companion` does not reach `pyfas` because the sidecar package never imports it. Omitting
these flags produces a binary that *starts and looks healthy* but reports
`result_analysis: {"enabled": false, "reason": "Fixture smoke-parse failed (pyfas installed?)…"}`,
silently disabling `result_parser.py`, `result_summarizer.py`, and `fast_ppl_plotter.py`.
`win32com.client` is pulled in because `pyfas/__init__.py` eagerly imports `pyfas.pilink`,
`pyfas.usc`, and `pyfas.sfc` when `os.name == "nt"`, which is also why `pywin32` is a hard
requirement of the `results` extra on Windows. Verify with Step 4 item 7.

The `results` extra is optional at runtime: without it, the core sidecar still starts and `publication_export` fails closed in `/api/capabilities`. Install `.[results]` before PyInstaller to ship result analysis and publication export. Publication styling is package-local and font selection falls back through installed CJK fonts to Matplotlib's bundled DejaVu Sans; no developer-home style script or user-home Pretendard file is required. The representative parser smoke fixture is package-local under `olga_companion/resources/results` and is included by both setuptools package data and PyInstaller's `--collect-data olga_companion` step.

## Step 2 — Icons

Generate the icon set from a 1024×1024 source (no HYSYS artwork):

```powershell
npx tauri icon path\to\olga-companion-icon.png
```

This populates `src-tauri/icons/` with the files `tauri.conf.json` already declares.

## Step 3 — Build

`resources/olga-toolkit/` is copied into the bundle **verbatim**, so any `__pycache__` left
behind by a local toolkit run ships inside the installer — and `.pyc` files embed the build
machine's absolute source path in `co_filename`, leaking a private developer path.

Toolkit subprocesses now run with `PYTHONDONTWRITEBYTECODE=1`, so a normal `npm run verify` no
longer leaves bytecode behind, and `test_bundled_toolkit_ships_no_compiled_bytecode` fails if
something does. If an older checkout still has a stray cache, remove exactly that directory before
building (it is generated and git-ignored):

```powershell
npm ci --ignore-scripts
npm run verify          # full gate must be green before packaging
npm run tauri:build     # wraps `tauri build`; produces .msi / .nsis under src-tauri\target\release\bundle
```

`tauri build` signs the updater artifacts and therefore needs the project's signing key. For a local
verification build without it, pass a config override that turns updater artifacts off (and, to keep
the user's installed app untouched, a different `identifier` and `productName`, which also gives the
build its own app-data directory and uninstall entry):

```powershell
npm run tauri:build -- --config verify-config.json   # {"identifier": "...verify", "productName": "... Verify", "bundle": {"createUpdaterArtifacts": false}}
```

WSL cannot run the Windows toolchain from its own PATH: call `cmd.exe /c` with the Rust toolchain's
`bin` directory prepended to `PATH`, and build the sidecar with `uv run --offline --frozen --isolated
--no-dev --python 3.11 --extra results --with pyinstaller pyinstaller ... --distpath/--workpath/--specpath`
pointing outside the repository, using absolute `--add-data` source paths.

## Step 4 — Packaging verification checklist (all mandatory)

1. **Sidecar startup:** launch the installed app; `GET http://127.0.0.1:8865/health` returns `"app": "OLGA Companion"`.
2. **Resource paths:** `/api/capabilities` reports `static_genkey` enabled via the bundled `resources/olga-toolkit` and `publication_export` enabled when `.[results]` was installed. The checked-in Tauri resource mapping installs the toolkit at `resources/olga-toolkit`, and the Rust host resolves that resource directory before setting `OLGA_TOOLKIT_DIR`. Verify one PNG/PDF export under a clean Windows user profile.
3. **Branding:** window title and installer metadata say `OLGA Companion`; the string `HYSYS` appears in no shipped file, i.e. no HYSYS branding, and no private dev-machine paths ship (automated by `tests/test_packaging_config.py::test_no_hysys_branding_or_private_paths_in_shipped_files`).
4. **Ports:** The packaged UI serves through the Tauri shell (`frontendDist`) and does not open an HTTP listener on 5273. The sidecar binds 8865 only. Port 5273 remains solely as the explicit development-origin value passed to the sidecar for local Vite QA; 5173/8765 appear nowhere.
5. **No cache/build contamination:** the bundle contains no `node_modules`, `__pycache__`, `var/sandbox`, or `var/exports` content.
6. Record the checklist run (installer hashes, screenshots, process and port observations) in the root `HANDOFF.md` or a scratch directory. Do not write it into `.litopencode/litgoal/lit-loop/`, which is an append-only ledger owned by another workflow.
8. **Port guard:** with something already listening on 8865, launch the installed app. It must exit without opening a window and leave `startup-error.log` in its app-local-data directory; a later successful start removes that file. Closing the window must leave no `olga-companion-sidecar.exe` and no listener on 8865.
9. **Update gate (isolated verify identity only, never a published update):** with a non-terminal `run.json` planted under the verify app-data `var\sandbox\runs\<id>`, invoking the `stop_sidecar` command from the webview must reject with `run_active` and leave the sidecar and port 8865 alone; with no such receipt it must resolve, leave no sidecar and no listener, and keep the window responsive; with the sidecar process suspended it must reject with `unconfirmed` after ~5 s while `IsHungAppWindow` stays false. To drive the command from outside, build the verify config with `app.windows[0].additionalBrowserArgs` containing `--remote-debugging-port=9222` (the `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` variable is ignored by this Tauri build) and evaluate `window.__TAURI_INTERNALS__.invoke('stop_sidecar')` over CDP. Never put that argument in the production configuration.
7. **Frozen toolkit re-entry (catches the silent `pyfas` gap):** `/health` must report
   `result_analysis.enabled == true`. A binary missing `--collect-all pyfas` still starts and
   answers `/health`, so checking that the app launches is **not** sufficient. Also exercise the
   re-entry path directly against a real non-empty `.ppl`:

   ```powershell
   $env:OLGA_TOOLKIT_DIR = "<install>\resources\olga-toolkit"
   & olga-companion-sidecar.exe --tool-script "$env:OLGA_TOOLKIT_DIR\scripts\result_parser.py" <real.ppl>
   ```

   Expect a `Type / Branches / Timesteps / Variables` summary and exit 0. Use a non-empty file:
   `pyfas` raises a bare `UnboundLocalError: nvar_idx` on a zero-byte `.ppl`, which looks like a
   packaging failure but is only an empty input.

## Configuration invariants (locked by tests on every host)

`tests/test_packaging_config.py` asserts: config parses; product name/window title; `bundle.active` with sidecar externalBin + olga-toolkit resources + icons; OLGA ports only (5273/8865, never 5173/8765); no HYSYS branding in `src-tauri/` or a built `frontend/dist`; this runbook keeps its verification checklist.

## v2 addendum — chat-first LLM layer (pip-only, no extra runtime to bundle)

The v2 re-architecture added a provider-agnostic LLM layer (`src/olga_companion/llm/`) and an agent runtime (`src/olga_companion/agent/`). Packaging impact is deliberately minimal:

- **Pure pip Python.** The LLM layer is ported from the HysysCompanion pattern, not the Claude Agent SDK — so there is **no Claude Code CLI / Node runtime to bundle**. New hard deps are `httpx` + `aiohttp` (declared in `pyproject.toml`); PyInstaller collects them like any wheel. `certifi` is an optional network-resilience fallback only.
- **OAuth tokens live outside the bundle** under `~/.olga_copilot/` (0600). No credential material is baked into the app; providers connect at runtime via the AI provider panel (Codex import from `$CODEX_HOME/auth.json`, or Copilot device flow).
- **Antigravity build secrets:** `src/olga_companion/llm/antigravity/_provisioned_secrets.py` is **gitignored** and absent from the tree. If Antigravity is to ship enabled, generate that file at build time on the Windows host (env → baked → fail-closed resolution in `antigravity/constants.py`); otherwise the provider stays honest-empty.
- **Windows-form OLGA detection:** `runner.OLGA_EXE_GLOBS` now includes native `C:\Program Files\Schlumberger\OLGA*\opi.exe` forms (the flat 2022.x layout, no `bin/`) alongside the WSL `/mnt/c/...` forms — so the packaged native-Windows sidecar detects a real install where the dev WSL globs would not. Verify detection on the Windows host as part of Step 4.
- **New QA-only file:** `scripts/fake_chat_sidecar.py` injects a scripted client for deterministic browser QA — it is **not shipped**; exclude it from the bundle.
- **Chat storage:** sessions persist to `var/chats/<id>.jsonl` (git-ignored, per-user local); ensure the packaged app can create `var/` under a writable app-data location on the Windows host.
