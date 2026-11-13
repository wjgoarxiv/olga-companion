import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { keepsUpdateHandle } from '../src/updateStages.mjs';

test('a re-check keeps the handle once a package is downloaded or the install was refused', () => {
  assert.equal(keepsUpdateHandle({ kind: 'downloaded', version: '0.2.0', bytes: 1 }), true);
  assert.equal(keepsUpdateHandle({ kind: 'blocked', version: '0.2.0', message: 'x' }), true);
});

test('a re-check may replace the handle in every other phase', () => {
  for (const kind of ['idle', 'checking', 'current', 'available', 'downloading', 'installing', 'unsupported', 'error']) {
    assert.equal(keepsUpdateHandle({ kind }), false, kind);
  }
  assert.equal(keepsUpdateHandle(undefined), false);
});

test('the panel consults the keep rule before it clears or closes anything', () => {
  const panel = readFileSync(new URL('../src/UpdatePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /const keepHandle = keepsUpdateHandle\(phase\);/);
  const check = panel.slice(panel.indexOf('const check = useCallback'), panel.indexOf('const download = useCallback'));
  const guard = check.indexOf('if (keepHandle)');
  assert.ok(guard !== -1, 'check() must use the keep rule');
  assert.ok(guard < check.indexOf('clearFoundUpdate()'), 'keep rule must precede clearFoundUpdate');
  assert.ok(guard < check.indexOf('.close()'), 'keep rule must precede close()');
});

test('Check is not disabled in the blocked phase', () => {
  const panel = readFileSync(new URL('../src/UpdatePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /const busy = phase\.kind === 'checking' \|\| phase\.kind === 'downloading' \|\| phase\.kind === 'installing';/);
});
