import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { installUpdate } from '../src/updateInstall.mjs';

const describe = (error) => (error instanceof Error ? error.message : String(error));

function steps(failures = {}) {
  const { stop, install, relaunch } = failures;
  const calls = [];
  return {
    calls,
    stop: async () => { calls.push('stop'); if ('stop' in failures) throw stop; },
    install: async () => { calls.push('install'); if ('install' in failures) throw install; },
    relaunch: async () => { calls.push('relaunch'); if ('relaunch' in failures) throw relaunch; },
  };
}

test('an idle backend is stopped, then installed, then relaunched, in that order', async () => {
  const s = steps();
  assert.deepEqual(await installUpdate({ ...s, describe }), { kind: 'installed' });
  assert.deepEqual(s.calls, ['stop', 'install', 'relaunch']);
});

for (const code of ['run_active', 'unconfirmed', 'stop_failed']) {
  test(`a native ${code} refusal never reaches the installer and keeps the reason`, async () => {
    const s = steps({ stop: { code, message: 'Open Run, then try again.' } });
    const outcome = await installUpdate({ ...s, describe });
    assert.deepEqual(outcome, { kind: 'blocked', code, message: 'Open Run, then try again.' });
    assert.deepEqual(s.calls, ['stop']);
  });
}

test('an unrecognised stop failure is a failure, and the installer still does not run', async () => {
  const s = steps({ stop: new Error('command stop_sidecar not found') });
  const outcome = await installUpdate({ ...s, describe });
  assert.equal(outcome.kind, 'failed');
  assert.equal(outcome.backendStopped, false);
  assert.deepEqual(s.calls, ['stop']);
});

test('a refusal shaped almost right is not trusted as a refusal', async () => {
  for (const bad of [{ code: 'run_active' }, { message: 'x' }, { code: 7, message: 'x' }, { code: 'other', message: 'x' }, null, 'run_active']) {
    const s = steps({ stop: bad });
    const outcome = await installUpdate({ ...s, describe });
    assert.equal(outcome.kind, 'failed', JSON.stringify(bad));
    assert.deepEqual(s.calls, ['stop']);
  }
});

test('an installer failure after the stop says the backend was stopped', async () => {
  const s = steps({ install: new Error('signature mismatch') });
  const outcome = await installUpdate({ ...s, describe });
  assert.equal(outcome.kind, 'failed');
  assert.equal(outcome.backendStopped, true);
  assert.deepEqual(s.calls, ['stop', 'install']);
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
