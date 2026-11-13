from __future__ import annotations

import json
from pathlib import Path
from typing import TypeAlias

from olga_companion import config

PROJECT = Path(__file__).parent.parent
TAURI_DIR = PROJECT / "src-tauri"
CONF = TAURI_DIR / "tauri.conf.json"
JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


def _conf() -> JsonObject:
    return json.loads(CONF.read_text(encoding="utf-8"))


def test_tauri_conf_parses_and_is_branded() -> None:
    conf = _conf()
    assert conf["productName"] == "OLGA Companion"
    assert conf["identifier"].startswith("com.")
    assert conf["app"]["windows"][0]["title"] == "OLGA Companion"


def test_no_hysys_branding_or_private_paths_in_shipped_files() -> None:
    scan_roots = [TAURI_DIR, PROJECT / "resources" / "olga-toolkit"]
    dist = PROJECT / "frontend" / "dist"
    if dist.exists():
        scan_roots.append(dist)
    for root in scan_roots:
        for path in root.rglob("*"):
            # Cargo's build output is regenerated, never shipped, and holds tens of thousands of files.
            if root == TAURI_DIR and path.relative_to(root).parts[0] == "target":
                continue
            if path.is_file() and path.suffix in {
                ".json",
                ".html",
                ".js",
                ".css",
                ".toml",
                ".rs",
                ".py",
                ".md",
                ".svg",
            }:
                text = path.read_text(encoding="utf-8", errors="replace").lower()
                assert "hysys" not in text, path
                assert "/home/" not in text, f"private path would ship in {path}"


def test_bundled_toolkit_ships_no_compiled_bytecode() -> None:
    """Tauri copies resources/olga-toolkit verbatim, so stray .pyc ships too.

    Compiled bytecode embeds the absolute source path of the build machine in
    ``co_filename``, which leaks a private developer path into the installer and
    also violates the runbook's no-``__pycache__`` rule. The text scan in
    ``test_no_hysys_branding_or_private_paths_in_shipped_files`` cannot catch it:
    that scan has a suffix allowlist which excludes ``.pyc``.
    """
    toolkit = PROJECT / "resources" / "olga-toolkit"
    bytecode = sorted(path.relative_to(toolkit) for path in toolkit.rglob("*.pyc"))
    assert not bytecode, f"compiled bytecode would ship in the bundle: {bytecode}"
    caches = sorted(
        path.relative_to(toolkit)
        for path in toolkit.rglob("__pycache__")
        if path.is_dir()
    )
    assert not caches, f"__pycache__ would ship in the bundle: {caches}"


def test_packaging_uses_olga_ports_only() -> None:
    text = CONF.read_text(encoding="utf-8")
    assert "5273" in text
    assert "8865" in text
    assert "5173" not in text
    assert "8765" not in text


def test_bundle_ships_sidecar_and_toolkit_resources() -> None:
    conf = _conf()
    bundle = conf["bundle"]
    assert bundle["active"] is True
    assert any("sidecar" in binary for binary in bundle["externalBin"])
    assert any("olga-toolkit" in resource for resource in bundle["resources"])
    assert bundle["icon"], "bundle icons must be declared"
    # Declared bundle resource paths must exist in the repo; icons are
    # generated on the Windows host (runbook step 2), which the runbook must
    # keep documenting.
    assert (PROJECT / "resources" / "olga-toolkit").is_dir()
    toolkit_scripts = PROJECT / "resources" / "olga-toolkit" / "scripts"
    toolkit_manifest = json.loads(
        (PROJECT / "resources" / "olga-toolkit" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    declared_scripts = [
        *toolkit_manifest["support_files"],
        *toolkit_manifest["scripts"],
    ]
    assert len(declared_scripts) == len(set(declared_scripts))
    for script in declared_scripts:
        assert (toolkit_scripts / script).is_file(), (
            f"packaged toolkit script is missing: {script}"
        )
    runbook = (PROJECT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")
    assert "tauri icon" in runbook


def test_runbook_declares_host_crate_bootstrap_and_build_script() -> None:
    runbook = (PROJECT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")
    assert "Step 0" in runbook, (
        "runbook must bootstrap the Tauri host crate before building"
    )
    assert "tauri-plugin-shell" in runbook
    package_json = json.loads((PROJECT / "package.json").read_text(encoding="utf-8"))
    assert package_json["scripts"]["tauri:build"]


def test_packaging_runbook_exists_with_verification_checklist() -> None:
    runbook = (PROJECT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")
    for required in (
        "PyInstaller",
        "tauri build",
        "WebView2",
        "no HYSYS",
        "8865",
        "5273",
    ):
        assert required in runbook, f"runbook missing: {required}"


def test_pyinstaller_payload_includes_checked_in_windows_broker_source() -> None:
    runbook = (PROJECT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")
    entrypoint = (PROJECT / "scripts" / "package_sidecar.py").read_text(
        encoding="utf-8"
    )
    broker_dir = PROJECT / "src" / "olga_companion" / "broker"
    broker_sources = tuple(sorted(broker_dir.glob("OlgaExplorerBroker*.cs")))

    assert "scripts\\package_sidecar.py" in runbook
    assert "from olga_companion.sidecar import main" in entrypoint
    assert "typing import ClassVar, Literal, override" not in (
        PROJECT / "src" / "olga_companion" / "case_publish_types.py"
    ).read_text(encoding="utf-8")
    assert len(broker_sources) == 3
    assert "--add-data" in runbook
    for broker_source in broker_sources:
        assert broker_source.name in runbook
    assert "olga_companion\\broker" in runbook


def test_publication_packaging_has_no_developer_asset_dependency() -> None:
    publication_source = (
        PROJECT / "src" / "olga_companion" / "publication_plot.py"
    ).read_text(encoding="utf-8")
    runbook = (PROJECT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")

    assert "/home/" not in publication_source
    assert ".local/share/fonts" not in publication_source
    assert "style_presets.py" not in publication_source
    assert '".[results]"' in runbook


def test_result_capability_smoke_fixture_is_package_local() -> None:
    fixture = (
        PROJECT / "src" / "olga_companion" / "resources" / "results" / "fixture.tpl"
    )
    results_source = (PROJECT / "src" / "olga_companion" / "results.py").read_text(
        encoding="utf-8"
    )
    packaging = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")

    assert fixture.is_file()
    assert 'Path(__file__).with_name("resources")' in results_source
    assert '"resources/results/fixture.tpl"' in packaging


def test_tauri_host_crate_and_sidecar_capability_are_checked_in() -> None:
    cargo = (TAURI_DIR / "Cargo.toml").read_text(encoding="utf-8")
    main = (TAURI_DIR / "src" / "main.rs").read_text(encoding="utf-8")
    capability = json.loads(
        (TAURI_DIR / "capabilities" / "default.json").read_text(encoding="utf-8")
    )

    assert 'tauri-plugin-shell = "2"' in cargo
    assert 'const SIDECAR_NAME: &str = "olga-companion-sidecar";' in main
    assert ".sidecar(SIDECAR_NAME)" in main
    assert "OLGA_APP_DATA_DIR" in main
    assert "OLGA_TOOLKIT_DIR" in main
    assert 'args(["/PID", &pid, "/T", "/F"])' in main
    assert capability["windows"] == ["main"]
    # Deliberately exact: the WebView gets the update surface and nothing else.
    # A wildcard here would quietly hand the frontend the whole plugin surface.
    assert capability["permissions"] == [
        "core:default",
        "core:window:allow-request-user-attention",
        "core:window:allow-set-progress-bar",
        "updater:default",
        "process:allow-restart",
    ]


def test_updater_is_configured_against_a_signed_https_release_channel() -> None:
    conf = _conf()
    cargo = (TAURI_DIR / "Cargo.toml").read_text(encoding="utf-8")
    main = (TAURI_DIR / "src" / "main.rs").read_text(encoding="utf-8")
    updater = conf["plugins"]["updater"]

    assert 'tauri-plugin-updater = "2"' in cargo
    assert 'tauri-plugin-process = "2"' in cargo
    assert "tauri_plugin_updater::Builder::new().build()" in main
    assert "tauri_plugin_process::init()" in main

    # An empty pubkey disables signature verification, which would let any
    # response on the endpoint replace the application.
    assert isinstance(updater["pubkey"], str) and len(updater["pubkey"]) > 40

    endpoints = updater["endpoints"]
    assert endpoints, "an updater with no endpoint can never find a release"
    for endpoint in endpoints:
        assert endpoint.startswith("https://"), endpoint
        assert endpoint.endswith("latest.json"), endpoint

    # Without this the build emits installers but no updater bundle or .sig,
    # so a release would be published that no client can verify or apply.
    assert conf["bundle"]["createUpdaterArtifacts"] is True


def test_download_and_install_are_separate_operator_decisions() -> None:
    panel = (PROJECT / "frontend" / "src" / "UpdatePanel.tsx").read_text(encoding="utf-8")

    # Fetching ~70 MB and replacing the binary underneath a running OLGA study
    # are different risks, so each hangs off its own explicit control. The fused
    # downloadAndInstall helper would collapse them back into one click.
    assert "update.download(" in panel
    assert "update.install()" in panel
    assert "downloadAndInstall" not in panel

    assert "onClick={() => download(phase.version)}" in panel
    assert "onClick={() => installAndRestart(phase.version)}" in panel

    # Nothing may start on mount. Match the call form, not the bare word: the
    # panel's own comment explaining this rule contains the identifier.
    assert "useEffect(" not in panel


def test_download_progress_is_reported_and_accessible() -> None:
    panel = (PROJECT / "frontend" / "src" / "UpdatePanel.tsx").read_text(encoding="utf-8")
    css = (PROJECT / "frontend" / "src" / "styles" / "settings.css").read_text(encoding="utf-8")

    assert 'role="progressbar"' in panel
    assert "aria-valuenow" in panel and "aria-valuemax" in panel
    # A server that sends no content length must still show motion rather than a
    # bar stuck at zero for the whole download.
    assert "is-indeterminate" in panel and ".update-progress.is-indeterminate" in css
    # Decoration is dropped, not the readout, when motion is unwelcome.
    assert "prefers-reduced-motion" in css


def test_packaged_runtime_state_uses_app_local_data(
    monkeypatch, tmp_path: Path
) -> None:
    app_data = tmp_path / "OLGA Companion"
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(app_data))

    assert config.project_root() == app_data.resolve()


def test_release_readme_covers_installation_safety_and_verification() -> None:
    readme = (PROJECT / "README.md").read_text(encoding="utf-8")

    for required in (
        "OLGA Companion",
        "Quick start",
        "Safety model",
        "Windows package",
        "npm run verify",
        "Known limitations",
    ):
        assert required in readme


def test_native_host_refuses_to_start_when_the_sidecar_port_is_taken() -> None:
    """A second listener on 8865 would leave the window attached to another program's state."""
    main = (TAURI_DIR / "src" / "main.rs").read_text(encoding="utf-8")
    spawn = main[main.index("fn spawn_sidecar") : main.index("fn terminate_sidecar")]

    assert "ensure_port_free(SIDECAR_PORT)?" in spawn
    assert spawn.index("ensure_port_free(SIDECAR_PORT)") < spawn.index(".spawn()")
    assert "StartupError::PortInUse" in main and "ErrorKind::AddrInUse" in main
    assert "startup-error.log" in main, "a windowless app must leave the reason on disk"
    assert "record_startup_failure" in main[main.index(".setup(") :]


def test_installing_an_update_stops_the_sidecar_before_the_windows_updater_exits() -> None:
    """The Windows updater calls process::exit(0), so RunEvent::Exit never reaches the host."""
    main = (TAURI_DIR / "src" / "main.rs").read_text(encoding="utf-8")
    panel = (PROJECT / "frontend" / "src" / "UpdatePanel.tsx").read_text(encoding="utf-8")

    # `async` keeps the blocking gate wait off the window-message thread (a stalled backend
    # froze the window for the whole wait when this was a plain sync command).
    assert "#[tauri::command(async)]\nfn stop_sidecar" in main
    assert main.index("update_gate::authorize_stop") < main.index("    stop();"), "no kill before a confirmed idle"
    assert "tauri::generate_handler![\n            stop_sidecar,\n            reveal_saved_report,\n            shutdown_app,\n            ack_close,\n            cancel_close\n        ]" in main
    assert ".manage(" in main and "SidecarSlot" in main
    # Same single-owner slot as the Exit path: whichever runs first stops it, the other finds it empty.
    assert main.count("take_sidecar(") >= 3
    install = panel[panel.index("const installAndRestart") :]
    assert "installUpdate(" in install
    assert install.index("invoke('stop_sidecar')") < install.index("update.install()")
    assert "backendStopped" in install, "a failed install after the stop must flag the stopped backend"
    assert "update.backendStopped" in panel, "the stopped-backend flag must render through the i18n dictionary"
    ko = (PROJECT / "frontend" / "src" / "i18n" / "ko.ts").read_text(encoding="utf-8")
    assert "'update.backendStopped'" in ko
    assert "OLGA Companion을 다시 여세요" in ko, "ko restart instruction must survive the i18n move"
    en = (PROJECT / "frontend" / "src" / "i18n" / "en.ts").read_text(encoding="utf-8")
    assert "'update.backendStopped'" in en
    assert "Reopen OLGA Companion" in en, "en must carry an English restart instruction for the same key"


ENGINE_PACKAGE = PROJECT / "src" / "olga_companion" / "pvt_engine"
NATIVE_TAB_FLAG = "OLGA_COMPANION_NATIVE_TAB"
PVT_HOOK = PROJECT / "scripts" / "pvt_native_tab_hook.py"


def test_the_sidecar_bundle_collects_the_independent_engine_and_its_adapter() -> None:
    """`--collect-submodules olga_companion` walks the package tree, so the engine must be a real
    subpackage, and PyInstaller's analysis sees the adapter's lazy imports on its own."""
    import pkgutil

    import olga_companion

    collected = {module.name for module in pkgutil.walk_packages(olga_companion.__path__, "olga_companion.")}
    assert {
        "olga_companion.native_tab",
        "olga_companion.pvt_engine",
        "olga_companion.pvt_engine.components",
        "olga_companion.pvt_engine.cubic",
        "olga_companion.pvt_engine.flash",
        "olga_companion.pvt_engine.properties",
        "olga_companion.pvt_engine.tab_writer",
        "olga_companion.pvt_engine.transport",
    } <= collected
    assert (ENGINE_PACKAGE / "__init__.py").is_file(), "setuptools and PyInstaller find packages by __init__.py"
    assert 'where = ["src"]' in (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    runbook = (PROJECT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")
    assert "--collect-submodules olga_companion" in runbook


def test_the_engine_needs_no_data_file_or_runtime_in_the_bundle() -> None:
    """Constants live in code. The only non-Python file is the MIT licence notice; no JRE is bundled."""
    stray = sorted(
        path.name
        for path in ENGINE_PACKAGE.rglob("*")
        if path.is_file() and path.suffix != ".py" and "__pycache__" not in path.parts
    )
    assert stray == ["LICENSE"]
    notice = (ENGINE_PACKAGE / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in notice
    assert "2026 Woojin Go" in notice
    runbook = (PROJECT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")
    assert "no JRE" in runbook or "no Java" in runbook
    assert "pyproject" not in str(stray)


def test_the_generator_flag_is_set_only_by_the_local_pvt_build_hook() -> None:
    """The release recipe, the Tauri host and the entry point never set the flag; the PVT-only
    PyInstaller runtime hook does, and the runbook says so."""
    hook = PVT_HOOK.read_text(encoding="utf-8")
    assert f'os.environ["{NATIVE_TAB_FLAG}"] = "1"' in hook
    assert "import" not in hook.replace("import os", "")
    for shipped in (
        TAURI_DIR / "src" / "main.rs",
        TAURI_DIR / "tauri.conf.json",
        PROJECT / "scripts" / "package_sidecar.py",
        PROJECT / "package.json",
    ):
        assert NATIVE_TAB_FLAG not in shipped.read_text(encoding="utf-8"), shipped
    runbook = (PROJECT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")
    assert NATIVE_TAB_FLAG in runbook and "--runtime-hook" in runbook and "pvt_native_tab_hook.py" in runbook
    release = runbook[runbook.index("## Step 1"): runbook.index("Copy the result to the Tauri external-binary")]
    assert "--runtime-hook" not in release, "the release recipe must stay hook-free"
    assert "never released" in runbook or "never ships" in runbook


def test_no_module_outside_the_flag_gate_imports_the_engine_at_import_time() -> None:
    """A release sidecar with the flag off must not even load the engine."""
    import ast

    allowed = {"native_tab.py", "__init__.py"}
    offenders = []
    for path in (PROJECT / "src" / "olga_companion").rglob("*.py"):
        if ENGINE_PACKAGE in path.parents or path.name in allowed and path.parent.name == "olga_companion":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            names = (
                [node.module or ""] + [alias.name for alias in node.names]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            )
            if any(name.endswith(("pvt_engine", "native_tab")) or name.startswith("pvt_engine") for name in names):
                offenders.append(str(path.relative_to(PROJECT)))
    assert offenders == []


# ----------------------------------------------------- lntabfix M2: no engine in a release sidecar

RELEASE_EXCLUDES = (
    "--exclude-module olga_companion.pvt_engine",
    "--exclude-module olga_companion.native_tab",
)


def _runbook() -> str:
    return (PROJECT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")


def _release_recipe() -> str:
    runbook = _runbook()
    return runbook[runbook.index("## Step 1"): runbook.index("Copy the result to the Tauri external-binary")]


def _pvt_delta() -> str:
    runbook = _runbook()
    start = runbook.index("**Independent table engine (local PVT Verify builds only).**")
    return runbook[start: runbook.index("**Why `--collect-all pyfas`")]


def test_the_release_recipe_excludes_the_engine_and_its_adapter() -> None:
    recipe = _release_recipe()
    for flag in RELEASE_EXCLUDES:
        assert flag in recipe, flag
    # The exclusion sits in the same PyInstaller command as the broad collect that would otherwise
    # pull the engine in; it is not a note in prose.
    command = recipe[recipe.index("pyinstaller"): recipe.index("scripts\\package_sidecar.py")]
    assert "--collect-submodules olga_companion" in command
    for flag in RELEASE_EXCLUDES:
        assert flag in command, flag


def test_the_excluded_names_are_real_modules() -> None:
    assert (PROJECT / "src" / "olga_companion" / "pvt_engine" / "__init__.py").is_file()
    assert (PROJECT / "src" / "olga_companion" / "native_tab.py").is_file()


def test_the_pvt_recipe_drops_the_exclusions_and_adds_the_hook() -> None:
    delta = " ".join(_pvt_delta().split())
    assert "Delete both `--exclude-module` lines" in delta
    assert "--runtime-hook" in delta and "pvt_native_tab_hook.py" in delta
    # The delta describes the PVT command; it never spells out an exclusion for it to carry.
    assert "--exclude-module olga_companion" not in delta


def test_the_local_pvt_build_script_keeps_the_engine_if_it_is_present_on_this_machine() -> None:
    script = Path("/mnt/c/Users/Woojin/AppData/Local/Temp/olga-claude-build/pvt-build.cmd")
    if not script.is_file():
        pytest.skip("the local PVT build script is not on this machine")
    text = script.read_text(encoding="utf-8", errors="replace")
    assert "--exclude-module olga_companion" not in text, "the PVT sidecar must keep the engine"
    assert "--collect-submodules olga_companion" in text


def test_the_runbook_records_why_the_exclusion_works_with_the_broad_collect() -> None:
    runbook = " ".join(_runbook().split())
    assert "excluding a package excludes its submodules" in runbook
    assert "6.21" in runbook, "the PyInstaller version the behaviour was checked against"
