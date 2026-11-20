// 0.1.20 review: the packaged window gets the session token from the shell, never over HTTP.
import test from 'node:test';
import assert from 'node:assert/strict';
import { isPackagedLocation, obtainSessionToken } from '../src/sessionTokenSource.mjs';

test('the packaged webview origins are recognised; the dev page is not', () => {
  assert.equal(isPackagedLocation({ hostname: 'tauri.localhost', protocol: 'http:' }), true);
  assert.equal(isPackagedLocation({ hostname: 'localhost', protocol: 'tauri:' }), true);
  assert.equal(isPackagedLocation({ hostname: '127.0.0.1', protocol: 'http:' }), false);
});

test('packaged: the shell command, and the HTTP route is never asked', async () => {
  const calls = [];
  const token = await obtainSessionToken({
    packaged: true,
    native: async () => { calls.push('native'); return 'shell-token'; },
    http: async () => { calls.push('http'); return 'http-token'; },
  });
  assert.equal(token, 'shell-token');
  assert.deepEqual(calls, ['native']);
});

test('packaged: a shell that has no token fails instead of falling back to HTTP', async () => {
  const calls = [];
  await assert.rejects(obtainSessionToken({
    packaged: true,
    native: async () => { calls.push('native'); throw new Error('session_token_unavailable'); },
    http: async () => { calls.push('http'); return 'http-token'; },
  }));
  assert.deepEqual(calls, ['native']);
});

test('dev page: the HTTP route', async () => {
  const token = await obtainSessionToken({ packaged: false, native: async () => 'x', http: async () => 'http-token' });
  assert.equal(token, 'http-token');
});
