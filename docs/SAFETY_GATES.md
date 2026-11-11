# OLGA Companion Safety Gates

## File mutation policy

- Never modify a user-owned `.genkey` source in place.
- All edits must happen on a sandbox copy.
- A `.bak` file must be created beside the sandbox working copy before writer execution.
- Validation must run after every edit before success is reported.
- The response must include whether the source hash changed.

## Trust-boundary input validation

- Reject missing files.
- Reject non-`.genkey` paths for M1 `.genkey` routes.
- Resolve case and PVT inputs only inside the canonical active workspace or app sandbox; reject escaping absolute paths and symlink escapes.
- Resolve result/report inputs only inside app-owned run and export roots.
- Reject missing keyword/key/value for modify-copy.
- Use allowlisted local script names; never accept a script path from the frontend.
- Require strict bounded subprocess timeouts (`1..604800` seconds, seven days) and return timeout evidence.
- Publish Save As output with extension matching, source hashing, no-clobber creation, or recoverable atomic replacement; never overwrite bytes that won a destination race.
- Existing-destination Save As retains two private safety copies in a random, same-filesystem directory adjacent to the selected folder. Every state root, lock, registry, retention directory, and captured file must pass verified POSIX `0700`/`0600` hardening or a protected Windows DACL restricted to the current identity, SYSTEM, and Administrators; inability to establish privacy fails closed. Request handling never unlinks captured names. A private write-ahead registry and OS file lock apply one app-global, cross-process hard cap of 512 MiB, 128 files, and 64 directories across every selected destination; a request that would exceed any limit fails before backup or staging. Retained copies and their registry entries require deliberate administrator cleanup while all sidecars are stopped.
- Opaque Save As recovery IDs map to path-bearing records only under `~/.olga_copilot/save-as-recovery/`; its root and every temporary/final record pass the same verified POSIX or protected-Windows-DACL boundary before use. Record hardening failure returns no recovery ID.

## Execution gates

### Live OLGA run

Disabled until all are true:
1. OLGA executable detected.
2. Case validation passes or user explicitly overrides.
3. Exact command preview is shown.
4. User explicitly approves.
5. Output directory is sandboxed.
6. Timeout/cancel behavior is tested.
7. Cancellation owns the entire launched process tree (POSIX process group for direct test/dev runtimes; Windows Job Object for native OLGA engines).

### Multiflash

Disabled until the app detects a supported Multiflash CLI/workflow. Until then, the app may prepare or inspect `.mfl`/`.tab` files only.

### Result analysis

Disabled until `.tpl`/`.ppl` parser dependencies are available and representative fixtures pass smoke tests.

### OPC/live control

Disabled until OLGA server mode, OPC dependencies, DCOM permissions, read/write separation, and explicit write approvals are verified.

## Misleading success prevention

- A command exit code of zero is not enough when validation output reports errors.
- UI success labels must reflect validation status, not only HTTP success.
- Disabled future capabilities must be displayed as gated, not hidden.
- Generated reports must cite source files and exact evidence.
