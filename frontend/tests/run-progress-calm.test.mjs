import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';

/* Owner report 2026-11-16 (0.1.9): while a run had no percentage yet the progress
 * area "kept blinking". Live PVT showed a translucent band over the whole meter,
 * text included, sweeping every 240 ms in three jumps (12 jumps a second). */

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const strip = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');

test('no sweep runs over the whole meter and its text', async () => {
  const css = strip(await read('../src/styles/motion.css'));
  assert.doesNotMatch(css, /\.run-progress-meter::after\s*\{[^}]*animation/);
});

test('only the bar track moves, and only while waiting for a first percentage', async () => {
  const source = await read('../src/RunProgress.tsx');
  assert.match(source, /className="run-progress-track"/);
  assert.match(source, /data-waiting=\{waiting \? 'true' : undefined\}/);
  const css = strip(await read('../src/styles/motion.css'));
  const rule = css.match(/([^{}]*\.run-progress-track\[data-waiting="true"\]::after)\s*\{([^}]*)\}/);
  assert.ok(rule, 'waiting indicator rule exists');
  assert.match(rule[1].trim(), /^html\[data-motion="full"\]/, 'Full motion only');
  assert.match(rule[2], /animation:\s*run-progress-glide\s+1600ms\s+var\(--ease-emphasized\)\s+infinite/, 'slow: about one step every 0.5 s');
  const keys = css.match(/@keyframes run-progress-glide\s*\{([\s\S]*?)\n\}/);
  assert.ok(keys, 'glide keyframes exist');
  assert.match(keys[1], /0%\s*\{\s*transform:\s*translateX\(0\)/, 'the marker starts visible, so it never vanishes and reappears');
});

test('a waiting track is a still, visible track without motion', async () => {
  const css = strip(await read('../src/styles/run.css'));
  assert.match(css, /\.run-progress-track\[data-waiting="true"\]\s*\{[^}]*background:\s*var\(--hairline-soft\)/);
});
