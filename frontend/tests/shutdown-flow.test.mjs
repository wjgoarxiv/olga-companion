import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';

const flow = await import('../src/shutdownFlow.mjs');

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('T5: a quiet shutdown walks saving -> stopping -> closing -> closed', () => {
  const f = flow.createShutdownFlow({ hasActiveRun: false });
  assert.equal(f.phase(), 'saving');
  f.event('saved');
  assert.equal(f.phase(), 'stopping');
  f.event('stopped');
  assert.equal(f.phase(), 'closing');
  f.event('exited');
  assert.equal(f.phase(), 'closed');
});

test('T5: an active run forces an in-app confirm first, never an implicit quit', () => {
  const f = flow.createShutdownFlow({ hasActiveRun: true });
  assert.equal(f.phase(), 'confirm');
  f.event('saved');
  assert.equal(f.phase(), 'confirm', 'stages do not advance from confirm');
  f.event('confirm_quit');
  assert.equal(f.phase(), 'saving');
});

test('T5: staying cancels back to idle', () => {
  const f = flow.createShutdownFlow({ hasActiveRun: true });
  f.event('confirm_stay');
  assert.equal(f.phase(), 'idle');
});

test('T5: confirm_quit without a confirm showing leaves a saving flow alone', () => {
  const f = flow.createShutdownFlow({ hasActiveRun: false });
  assert.equal(f.phase(), 'saving');
  f.event('confirm_quit');
  assert.equal(f.phase(), 'saving');
});

test('T5: failure parks with a reason and retry returns to the start', () => {
  const f = flow.createShutdownFlow({ hasActiveRun: false });
  f.event('saved');
  f.event('fail', 'stop_failed');
  assert.equal(f.phase(), 'failed');
  assert.equal(f.reason(), 'stop_failed');
  f.event('retry');
  assert.equal(f.phase(), 'saving');
});

test('T5: stage order is saving, stopping, closing', () => {
  assert.deepEqual([...flow.SHUTDOWN_STAGES], ['saving', 'stopping', 'closing']);
  assert.equal(flow.stageProgress('saving'), 1 / 3);
  assert.equal(flow.stageProgress('closing'), 1);
});

test('T5: shutdown copy exists in ko and en', () => {
  for (const key of [
    'shutdown.title', 'shutdown.stage.saving', 'shutdown.stage.stopping',
    'shutdown.stage.closing', 'shutdown.confirmTitle', 'shutdown.confirmBody',
    'shutdown.confirmQuit', 'shutdown.confirmStay', 'shutdown.failed',
  ]) {
    assert.ok(ko[key], `ko ${key}`);
    assert.ok(en[key], `en ${key}`);
    assert.notEqual(ko[key], en[key], `${key} is translated`);
  }
});

test('T5: ShutdownOverlay confirms in-app and shows stages, Rust gates the close', async () => {
  const [overlay, hook, layer, main, caps, css] = await Promise.all([
    read('../src/ShutdownOverlay.tsx'),
    read('../src/useShutdownGate.tsx'),
    read('../src/AppLifecycleLayer.tsx'),
    read('../../src-tauri/src/main.rs'),
    read('../../src-tauri/capabilities/default.json'),
    read('../src/styles/boot.css'),
  ]);
  assert.match(overlay, /alertdialog/, 'confirm is an in-app dialog');
  assert.match(overlay, /shutdown\.confirm/, 'confirm copy comes from i18n');
  assert.doesNotMatch(overlay, /window\.confirm/, 'never the native blocking confirm');
  assert.match(overlay, /shutdown\.stage\./, 'stages come from i18n');
  assert.match(overlay, /progressbar/, 'progress is exposed to AT');
  assert.match(hook, /ShutdownOverlay/, 'the shutdown hook renders the overlay');
  assert.match(hook, /app-close-requested/, 'the shutdown hook listens for the Rust close event');
  assert.match(layer, /useShutdownGate/, 'the lifecycle layer owns shutdown wiring');
  assert.match(hook, /ack_close/, 'every close request is acknowledged so the fallback stays armed only for silence');
  assert.match(hook, /cancel_close/, 'Stay abandons the shutdown on the Rust side too');
  assert.match(hook, /1500/, 'the active-run probe is bounded so the confirm still shows in time');
  assert.match(hook, /phase\(\) === 'saving'/, 'a quiet shutdown proceeds without a confirm');
  assert.match(main, /fn ack_close/, 'Rust exposes the close acknowledgement');
  assert.match(main, /fn cancel_close/, 'Rust exposes the close cancellation');
  assert.match(main, /CLOSE_GENERATION/, 'the fallback is scoped to its own close request');
  assert.match(main, /CloseRequested/, 'Rust intercepts the window close');
  assert.match(main, /prevent_close/, 'Rust keeps the window until shutdown finishes');
  assert.match(main, /app-close-requested/, 'Rust tells the webview to shut down');
  assert.match(main, /shutdown_app/, 'Rust exposes a shutdown command');
  assert.match(main, /10/, 'a fallback timer forces exit when the webview is silent');
  assert.match(caps, /request-user-attention/, 'taskbar flash capability is present');
  assert.match(css, /shutdown/, 'shutdown has styles in boot.css');
  assert.match(css, /prefers-reduced-motion/, 'shutdown motion collapses under reduced motion');
});
