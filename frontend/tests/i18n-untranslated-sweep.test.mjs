import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SCRIPT = resolve(HERE, '..', '..', 'scripts', 'find_untranslated_ui.mjs');

// The script exits 1 while any non-allow-listed literal remains in frontend/src/**/*.tsx.
test('no untranslated UI literals remain', () => {
  const run = spawnSync(process.execPath, [SCRIPT], { encoding: 'utf8' });
  assert.equal(run.status, 0, `untranslated UI strings remain:\n${run.stdout}`);
});
