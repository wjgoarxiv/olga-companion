import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { installUpdate } from '../src/updateInstall.mjs';

const describe = (error) => (error instanceof Error ? error.message : String(error));

function steps(failures = {}) {
  const { apply, relaunch } = failures;
  const calls = [];
  return {
    calls,
    apply: async () => { calls.push('apply'); if ('apply' in failures) throw apply; },
    relaunch: async () => { calls.push('relaunch'); if ('relaunch' in failures) throw relaunch; },
  };
}

test('an idle backend is stopped, then installed, then relaunched, in that order', async () => {
  const s = steps();
  assert.deepEqual(await installUpdate({ ...s, describe }), { kind: 'installed' });
  assert.deepEqual(s.calls, ['apply', 'relaunch']);
});

for (const code of ['run_active', 'unconfirmed', 'stop_failed']) {
  test(`a native ${code} refusal never reaches the installer and keeps the reason`, async () => {
    const s = steps({ apply: { code, message: 'Open Run, then try again.' } });
    const outcome = await installUpdate({ ...s, describe });
    assert.deepEqual(outcome, { kind: 'blocked', code, message: 'Open Run, then try again.' });
    assert.deepEqual(s.calls, ['apply']);
  });
}

test('an unrecognised stop failure is a failure, and the installer still does not run', async () => {
  const s = steps({ apply: new Error('command install_update not found') });
  const outcome = await installUpdate({ ...s, describe });
  assert.equal(outcome.kind, 'failed');
  assert.equal(outcome.backendStopped, false);
  assert.deepEqual(s.calls, ['apply']);
});

test('a refusal shaped almost right is not trusted as a refusal', async () => {
  for (const bad of [{ code: 'run_active' }, { message: 'x' }, { code: 7, message: 'x' }, { code: 'other', message: 'x' }, null, 'run_active']) {
    const s = steps({ apply: bad });
    const outcome = await installUpdate({ ...s, describe });
    assert.equal(outcome.kind, 'failed', JSON.stringify(bad));
    assert.equal(outcome.backendStopped, false, JSON.stringify(bad));
    assert.deepEqual(s.calls, ['apply']);
  }
});

test('an installer failure after the stop says the backend was stopped', async () => {
  const s = steps({ apply: { code: 'install_failed', message: 'signature mismatch' } });
  const outcome = await installUpdate({ ...s, describe: (e) => e.message });
  assert.deepEqual(outcome, { kind: 'failed', message: 'signature mismatch', backendStopped: true });
  assert.deepEqual(s.calls, ['apply']);
});

test('the panel routes Install through the guarded flow and keeps the button after a refusal', () => {
  const panel = readFileSync(new URL('../src/UpdatePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /installUpdate\(/);
  assert.doesNotMatch(panel, /await invoke\('stop_sidecar'\)/);
  assert.match(panel, /kind: 'blocked'/);
  assert.match(panel, /phase\.kind === 'downloaded' \|\| phase\.kind === 'blocked'/);
  assert.match(panel, /phase\.kind === 'blocked' && phase\.message/);
});

test('focus is handed back after a refusal or failure, and update buttons are touch sized on phones', () => {
  const panel = readFileSync(new URL('../src/UpdatePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /installButton\.current\?\.focus\(\)/);
  assert.match(panel, /checkButton\.current\?\.focus\(\)/);
  const css = readFileSync(new URL('../src/styles/settings.css', import.meta.url), 'utf8');
  const phone = css.slice(css.indexOf('@media (max-width: 760px)'));
  assert.match(phone, /\.settings-view \.update-actions button\s*\{\s*min-height:\s*44px/);
});
