# OLGA toolkit adapter resources

The sidecar uses the OLGA toolkit's Python scripts through a bounded adapter. The app never accepts arbitrary script paths from the frontend; it uses an allowlisted script map (see `manifest.json`).

The toolkit location is resolved from the `OLGA_TOOLKIT_DIR` environment variable, falling back to the development default compiled into the sidecar (`src/olga_companion/config.py`). Packaged builds must set `OLGA_TOOLKIT_DIR` to the bundled toolkit resources in the sidecar spawn wiring (`docs/PACKAGING.md`, Step 0):

`OLGA_TOOLKIT_DIR=/path/to/olga-toolkit`

The allowlisted scripts and their shared parser are vendored under `scripts/`
so that an installed desktop build does not depend on a developer-specific
skill checkout. Runtime capability checks validate the files before enabling
static GENKEY operations.
