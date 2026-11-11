from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def hash_descriptor(ctx: Any, descriptor: int) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = ctx.os.read(descriptor, ctx._RUNTIME_COPY_CHUNK_BYTES)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def contained_runtime_matches(ctx: Any, path: Path, expected_sha256: str) -> bool:
    flags = ctx.os.O_RDONLY | getattr(ctx.os, "O_BINARY", 0) | getattr(ctx.os, "O_NOFOLLOW", 0)
    descriptor = ctx.os.open(path, flags)
    try:
        if not ctx.stat.S_ISREG(ctx.os.fstat(descriptor).st_mode):
            return False
        return ctx._hash_descriptor(descriptor) == expected_sha256
    finally:
        ctx.os.close(descriptor)


def prepare_contained_runtime(
    ctx: Any,
    run_dir: Path,
    detection: dict[str, Any],
) -> tuple[Path, dict[str, str]]:
    approved_path = Path(str(detection["exe"]))
    approved_sha256 = str(detection.get("sha256") or "")
    if len(approved_sha256) != 64:
        raise ctx.OlgaInputError("Approved OLGA runtime content hash is missing or invalid.")
    suffix = approved_path.suffix if detection.get("kind") == "script" else approved_path.suffix.lower()
    contained_path = run_dir / f"approved-runtime{suffix}"
    source_flags = (
        ctx.os.O_RDONLY
        | getattr(ctx.os, "O_BINARY", 0)
        | getattr(ctx.os, "O_NOFOLLOW", 0)
    )
    target_flags = (
        ctx.os.O_WRONLY
        | ctx.os.O_CREAT
        | ctx.os.O_EXCL
        | getattr(ctx.os, "O_BINARY", 0)
        | getattr(ctx.os, "O_NOFOLLOW", 0)
    )
    source_descriptor = ctx.os.open(approved_path, source_flags)
    target_descriptor: int | None = None
    try:
        source_stat = ctx.os.fstat(source_descriptor)
        if not ctx.stat.S_ISREG(source_stat.st_mode):
            raise ctx.OlgaInputError("Approved OLGA runtime must be a regular file.")
        executable_mode = ctx.stat.S_IMODE(source_stat.st_mode)
        target_descriptor = ctx.os.open(contained_path, target_flags, executable_mode)
        digest = hashlib.sha256()
        while True:
            chunk = ctx.os.read(source_descriptor, ctx._RUNTIME_COPY_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            remaining = memoryview(chunk)
            while remaining:
                written = ctx.os.write(target_descriptor, remaining)
                if written <= 0:
                    raise OSError("short write while containing approved runtime")
                remaining = remaining[written:]
        ctx.os.fchmod(target_descriptor, executable_mode)
        ctx.os.fsync(target_descriptor)
    finally:
        ctx.os.close(source_descriptor)
        if target_descriptor is not None:
            ctx.os.close(target_descriptor)

    copied_sha256 = digest.hexdigest()
    if copied_sha256 != approved_sha256 or not ctx._contained_runtime_matches(
        contained_path,
        approved_sha256,
    ):
        contained_path.unlink(missing_ok=True)
        raise ctx.OlgaInputError(
            "Approved OLGA runtime content changed while preparing the contained artifact."
        )
    return contained_path, {"name": contained_path.name, "sha256": copied_sha256}
