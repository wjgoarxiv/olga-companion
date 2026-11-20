// 0.1.20 row 12: the page downloads and installs only through the app's own gated commands.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { downloadNative, installNative } from '../src/updateNative.mjs';

function fakeInvoke(reply = async () => undefined) {
  const calls = [];
  return { calls, invoke: async (command, args) => { calls.push([command, args]); return reply(command, args); } };
}

class FakeChannel { constructor() { this.onmessage = null; } }

test('download goes through download_update and forwards its progress', async () => {
  const seen = [];
  const fake = fakeInvoke(async (_command, args) => {
    args.onEvent.onmessage({ event: 'Started', data: { contentLength: 10 } });
    args.onEvent.onmessage({ event: 'Progress', data: { chunkLength: 4 } });
  });
  await downloadNative('0.1.20', (event) => seen.push(event.event), { invoke: fake.invoke, Channel: FakeChannel });
  assert.deepEqual(fake.calls.map(([command, args]) => [command, args.version]), [['download_update', '0.1.20']]);
  assert.deepEqual(seen, ['Started', 'Progress']);
});

test('install goes through install_update, which runs the stop gate itself', async () => {
  const fake = fakeInvoke();
  await installNative('0.1.20', { invoke: fake.invoke });
  assert.deepEqual(fake.calls, [['install_update', { version: '0.1.20' }]]);
});

test('the window may only check for updates; download and install are not granted to the page', () => {
  const capability = JSON.parse(readFileSync(new URL('../../src-tauri/capabilities/default.json', import.meta.url), 'utf8'));
  const updater = capability.permissions.filter((permission) => String(permission).startsWith('updater:'));
  assert.deepEqual(updater, ['updater:allow-check']);
});

test('a native refusal keeps its own message, and a stale one is named as stale', async () => {
  const { describeNativeError } = await import('../src/updateNative.mjs');
  assert.deepEqual(describeNativeError({ code: 'install_failed', message: 'signature mismatch' }), { stale: false, message: 'signature mismatch' });
  assert.deepEqual(describeNativeError({ code: 'stale', message: 'x' }), { stale: true, message: null });
  assert.deepEqual(describeNativeError(new Error('boom')), { stale: false, message: 'boom' });
  assert.deepEqual(describeNativeError('plain'), { stale: false, message: 'plain' });
  assert.deepEqual(describeNativeError(42), { stale: false, message: null });
});
