import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';

const gate = await import('../src/bootGate.mjs');

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function harness(timeoutMs = 45_000) {
  let now = 0;
  const g = gate.createBootGate({ now: () => now, timeoutMs });
  return { g, advance: (ms) => { now += ms; } };
}

test('T4: boot gate walks starting -> connecting -> ready', () => {
  const { g } = harness();
  assert.equal(g.phase(), 'starting');
  g.event('health_ok');
  assert.equal(g.phase(), 'connecting');
  g.event('ready_ok');
  assert.equal(g.phase(), 'ready');
  assert.ok(g.isReady());
});

test('T4: a fast online signal still reaches ready without intermediate stages', () => {
  const { g } = harness();
  g.event('ready_ok');
  assert.equal(g.phase(), 'ready');
});

test('T4: a late online signal recovers a failed gate back to ready', () => {
  const { g, advance } = harness(45_000);
  advance(45_000);
  assert.equal(g.checkTimeout(), true);
  assert.equal(g.phase(), 'failed');
  g.event('ready_ok');
  assert.equal(g.phase(), 'ready');
  assert.equal(g.reason(), null);
});

test('T4: 45 s without ready fails with timeout', () => {
  const { g, advance } = harness(45_000);
  g.event('health_ok');
  advance(44_999);
  assert.equal(g.checkTimeout(), false);
  assert.equal(g.phase(), 'connecting');
  advance(1);
  assert.equal(g.checkTimeout(), true);
  assert.equal(g.phase(), 'failed');
  assert.equal(g.reason(), 'timeout');
});

test('T4: exhausted runtime retries fail offline, retry restarts the clock', () => {
  const { g, advance } = harness();
  g.event('health_ok');
  advance(5_000);
  g.event('exhausted');
  assert.equal(g.phase(), 'failed');
  assert.equal(g.reason(), 'offline');
  g.event('retry');
  assert.equal(g.phase(), 'starting');
  assert.equal(g.elapsedMs(), 0);
});

test('T4: poll backoff starts at 250 ms and caps at 1 s', () => {
  assert.equal(gate.bootPollDelayMs(1), 250);
  assert.equal(gate.bootPollDelayMs(2), 500);
  assert.equal(gate.bootPollDelayMs(3), 1000);
  assert.equal(gate.bootPollDelayMs(9), 1000);
});

test('T4: boot overlay copy exists in ko and en', () => {
  for (const key of [
    'boot.stage.starting', 'boot.stage.connecting',
    'boot.failedTitle', 'boot.reason.offline', 'boot.reason.timeout',
    'boot.reason.unavailable', 'boot.retry', 'boot.bundle', 'boot.loading',
  ]) {
    assert.ok(ko[key], `ko ${key}`);
    assert.ok(en[key], `en ${key}`);
    assert.notEqual(ko[key], en[key], `${key} is translated`);
  }
});

test('T4: BootOverlay lifts away, blocks input while pending, offers bundle on failure', async () => {
  const [overlay, hook, layer, app, css] = await Promise.all([
    read('../src/BootOverlay.tsx'),
    read('../src/useBootGate.tsx'),
    read('../src/AppLifecycleLayer.tsx'),
    read('../src/App.tsx'),
    read('../src/styles/boot.css'),
  ]);
  assert.match(overlay, /boot\.stage\./, 'stage label comes from i18n');
  assert.match(overlay, /leaving/, 'ready lifts away via the leaving prop');
  assert.match(hook, /240/, 'ready lifts away in ~240 ms');
  assert.match(css, /240ms/, 'leaving transition is ~240 ms');
  assert.match(hook, /\/api\/diagnostics\/bundle/, 'failed offers a diagnostics bundle');
  assert.match(overlay, /boot\.retry/, 'failed offers a retry');
  assert.match(hook, /BootOverlay/, 'the boot hook renders the overlay');
  assert.match(layer, /useBootGate/, 'the lifecycle layer owns boot wiring');
  assert.match(app, /AppLifecycleLayer/, 'App mounts the lifecycle layer in a couple of lines');
  assert.match(app, /<\/div>\s*<AppLifecycleLayer/, 'the layer renders outside the inert workbench');
  assert.doesNotMatch(hook, /exhausted/, 'a first offline is not terminal; only the 45 s timeout fails');
  assert.match(overlay, /failure !== 'offline'/, 'the offline failure hides the bundle button');
  assert.match(overlay, /inert/, 'overlay holds the workbench inert until ready');
  assert.match(css, /prefers-reduced-motion/, 'boot motion collapses under reduced motion');
  assert.doesNotMatch(css, /transition[^;{]*\b(width|height|top|left)\b/, 'boot animates transform/opacity only');
});
