// `npm run tauri:build`: run `tauri build` with this machine's paths remapped out of the binary.
//
// Third-party crates embed panic! locations from `file!()`, which otherwise bakes
// `<CARGO_HOME>\registry\src\...` (and so the build account name) into olga-companion.exe.
// The prefix is computed here, so the repository never names a build account.
import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

// Bytecode left by a local Python run records the absolute source path; it must not reach the bundle.
const dropBytecode = (dir) => {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const path = join(dir, entry.name);
    if (entry.name === '__pycache__') rmSync(path, { recursive: true, force: true });
    else dropBytecode(path);
  }
};
dropBytecode(fileURLToPath(new URL('../resources', import.meta.url)));

const cargoHome = process.env.CARGO_HOME || join(homedir(), '.cargo');
// rustc lets the last matching prefix win, so the broad home remap comes first.
const remaps = [
  `--remap-path-prefix=${homedir()}=/home`,
  `--remap-path-prefix=${join(cargoHome, 'registry', 'src')}=/cargo-registry`,
  `--remap-path-prefix=${join(cargoHome, 'git', 'checkouts')}=/cargo-git`,
];
// The encoded form keeps a path with spaces as one flag; cargo prefers it over RUSTFLAGS.
const inherited = process.env.CARGO_ENCODED_RUSTFLAGS
  ? process.env.CARGO_ENCODED_RUSTFLAGS.split('\x1f')
  : (process.env.RUSTFLAGS ?? '').split(' ').filter(Boolean);
const encoded = [...inherited, ...remaps].join('\x1f');
// Setting the variable makes cargo ignore rustflags from its config files, so say so.
for (const name of ['config.toml', 'config']) {
  const file = join(cargoHome, name);
  if (existsSync(file) && /rustflags/.test(readFileSync(file, 'utf8'))) {
    console.warn(`${file} sets rustflags, which this build ignores; put them in RUSTFLAGS instead.`);
  }
}

const cli = createRequire(import.meta.url).resolve('@tauri-apps/cli/tauri.js');
const result = spawnSync(process.execPath, [cli, 'build', ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: { ...process.env, CARGO_ENCODED_RUSTFLAGS: encoded },
});
process.exit(result.status ?? 1);
