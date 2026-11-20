"""PyInstaller entry point for the packaged OLGA Companion sidecar."""

from olga_companion.sidecar import main


if __name__ == "__main__":
    raise SystemExit(main())
