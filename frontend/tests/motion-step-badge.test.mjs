import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// v0111 leftovers task 3: the three finite motion candidates marked "Yes" in
// ui-state-matrix.md (step done check, next-action ring, tab badge appear).
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const strip = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const KEYFRAMES = ['step-done-pop', 'step-next-ring-a', 'step-next-ring-b', 'ui-badge-in'];

function keyframeBody(css, name) {
  const start = css.indexOf(`@keyframes ${name}`);
  assert.ok(start >= 0, `@keyframes ${name} exists in motion.css`);
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(open + 1, i);
    }
  }
  throw new Error(`unbalanced @keyframes ${name}`);
}

function split(css) {
  const reduceAt = css.indexOf('@media (prefers-reduced-motion: reduce)');
  assert.ok(reduceAt >= 0, 'motion.css has a reduced-motion block');
  return { main: css.slice(0, reduceAt), reduce: css.slice(reduceAt) };
}

// Every rule in the main part whose animation declaration names the keyframe.
function usersOf(main, name) {
  return [...main.matchAll(/([^{}@]+)\{([^{}]*)\}/g)]
    .filter((m) => new RegExp(`animation\\s*:[^;}]*\\b${name}\\b`).test(m[2]))
    .map((m) => ({ selector: m[1].trim(), body: m[2] }));
}

test('each new keyframe exists, is used by a finite one-shot animation and avoids layout properties', async () => {
  const { main } = split(strip(await read('../src/styles/motion.css')));
  for (const name of KEYFRAMES) {
    const body = keyframeBody(main, name);
    assert.doesNotMatch(body, /\b(width|height|top|left|right|bottom|margin|padding)\b/, `@keyframes ${name} never moves layout`);
    const users = usersOf(main, name);
    assert.ok(users.length > 0, `${name} is used by a rule`);
    for (const { selector, body: rule } of users) {
      assert.doesNotMatch(rule, /\binfinite\b/, `${selector}: ${name} must not loop`);
      assert.match(rule, /var\(--ease-ui\)/, `${selector}: ${name} reads the --ease-ui token`);
      assert.match(rule, /var\(--d-ui\)/, `${selector}: ${name} reads the --d-ui token`);
    }
  }
});

test('step done check pops once: transform scale 0.9 to 1 on the done step number', async () => {
  const { main } = split(strip(await read('../src/styles/motion.css')));
  const body = keyframeBody(main, 'step-done-pop');
  assert.match(body, /scale\(\s*0?\.9\s*\)/, 'starts at 0.9');
  assert.doesNotMatch(body, /opacity/, 'transform only');
  const [rule] = usersOf(main, 'step-done-pop');
  assert.match(rule.selector, /\.step-cell\.is-done\s+\.step-num/, 'plays on the done step check');
  assert.doesNotMatch(rule.selector, /\.(approve|run-go|run-actions|approval)/, 'never on approval controls');
});

test('next-action ring is a hard 2px box-shadow ring (blur 0), two iterations, never on approval or run controls', async () => {
  const { main } = split(strip(await read('../src/styles/motion.css')));
  for (const name of ['step-next-ring-a', 'step-next-ring-b']) {
    const body = keyframeBody(main, name);
    assert.match(body, /box-shadow:\s*0 0 0 2px var\(--focus\)/, `${name} starts from a hard 2px ring`);
    assert.doesNotMatch(body, /opacity/, `${name} does not fade or blink`);
    assert.doesNotMatch(body, /box-shadow:[^;]*\b\d+px\s+\d+px\s+[1-9]\d*px/, `${name} has no blurred layer`);
    const [rule] = usersOf(main, name);
    assert.match(rule.selector, /\.step-next\[data-ring=/, `${name} plays on the step-next button`);
    assert.match(rule.body, /var\(--ease-ui\)\s+2\b/, `${name} runs exactly 2 iterations`);
    assert.doesNotMatch(rule.selector, /\.(approve|run-go|run-actions|approval)/, `${name} never targets approval or run controls`);
  }
  const bar = await read('../src/shell/StepBar.tsx');
  assert.match(bar, /data-ring=\{/, 'StepBar retriggers the ring through a data-ring toggle (no remount, focus stays)');
  assert.match(bar, /decision\.kind/, 'the toggle follows the next action');
});

test('tab badge appears once with the ui-pop-in shape: fade up, monotonic opacity', async () => {
  const { main } = split(strip(await read('../src/styles/motion.css')));
  const body = keyframeBody(main, 'ui-badge-in');
  assert.match(body, /opacity:\s*0/, 'fades in');
  assert.match(body, /translateY\(6px\)/, 'rises 6px');
  const [rule] = usersOf(main, 'ui-badge-in');
  assert.match(rule.selector, /\.ui-tab-badge\[data-kind\]/, 'status badges only');
  const tabs = await read('../src/ui/Tabs.tsx');
  assert.match(tabs, /key=\{item\.badge\}/, 'the badge remounts when its text changes, so it appears once per change');
});

test('every new animated selector is cancelled in the reduced-motion block', async () => {
  const { main, reduce } = split(strip(await read('../src/styles/motion.css')));
  assert.match(reduce, /animation:\s*none/, 'reduced motion stops animations');
  for (const name of KEYFRAMES) {
    for (const { selector } of usersOf(main, name)) {
      for (const part of selector.split(',').map((s) => s.trim())) {
        assert.ok(reduce.includes(part), `reduced motion covers ${part} (${name})`);
      }
    }
  }
});
