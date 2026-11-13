import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// Lane B / T3: app-wide micro-interactions. Tokens live in motion.css; the
// approval state change lives in chat-tools.css (motion.css must never target
// approval controls — see neo-motion-decor.test.mjs).
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const strip = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const TOUCHED = ['../src/styles/motion.css', '../src/styles/chat-tools.css', '../src/styles/controls.css'];
const NEW_KEYFRAMES = ['ui-pop-in', 'ui-list-in'];

function keyframeBody(css, name) {
  const start = css.indexOf(`@keyframes ${name}`);
  assert.ok(start >= 0, `@keyframes ${name} exists`);
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

test('motion tokens exist in motion.css with the T3 values', async () => {
  const css = strip(await read('../src/styles/motion.css'));
  for (const [token, value] of [
    ['--dur-1', '90ms'],
    ['--dur-2', '160ms'],
    ['--dur-3', '240ms'],
    ['--ease-out', 'cubic-bezier(.2,.8,.2,1)'],
    ['--ease-spring', 'cubic-bezier(.34,1.56,.64,1)'],
  ]) {
    assert.match(css, new RegExp(`${token}:\\s*${value.replace(/[().,]/g, '\\$&')}`), `${token} is ${value}`);
  }
});

test('buttons and IconButtons press to scale .97 and lift on hover (transform only)', async () => {
  const css = strip(await read('../src/styles/motion.css'));
  assert.match(css, /:active[^{]*\{[^}]*transform:\s*scale\(\s*0?\.97\s*\)/s, 'press is scale(.97)');
  assert.match(css, /:hover[^{]*\{[^}]*transform:\s*translateY\(-1px\)/s, 'hover lifts 1px');
  assert.match(css, /\.ui-button[^{]*:active/, 'the press rule covers .ui-button');
  assert.match(css, /\.ui-iconbutton[^{]*:active/, 'the press rule covers .ui-iconbutton');
});

test('tabs and Segmented have a measured sliding indicator driven by transform only', async () => {
  const css = strip(await read('../src/styles/motion.css'));
  for (const indicator of ['.ui-tab-indicator', '.ui-segmented-indicator']) {
    const escaped = indicator.replace('.', '\\.');
    assert.match(css, new RegExp(`${escaped}\\s*\\{[^}]*transform:\\s*translateX\\(var\\(--ind-x`), `${indicator} slides from a measured offset`);
    assert.match(css, new RegExp(`${escaped}[^{]*\\{[^}]*transition:[^;}]*transform`), `${indicator} eases with a transform transition`);
  }
  assert.doesNotMatch(css, /\.ui-tab\[aria-selected="true"\]::(?:before|after)/, 'no animated edge layers on the active tab (flash-safety)');
  for (const [source, indicator] of [['../src/ui/Tabs.tsx', 'ui-tab-indicator'], ['../src/ui/Segmented.tsx', 'ui-segmented-indicator']]) {
    const tsx = await read(source);
    assert.match(tsx, new RegExp(indicator), `${source} renders a measured indicator`);
    assert.match(tsx, /offsetLeft - \w+\.clientLeft/, `${source} positions it from the selected control`);
    assert.match(tsx, /offsetWidth/, `${source} sizes it from the selected control`);
    assert.match(tsx, /aria-hidden="true"/, `${source} hides the bar from assistive tech`);
  }
});

test('popovers, menus and palettes open with fade + 6px translate', async () => {
  const css = strip(await read('../src/styles/motion.css'));
  for (const selector of ['.ui-popover', '.ui-menu', '.ui-palette']) {
    assert.match(css, new RegExp(`${selector.replace('.', '\\.')}[^{]*\\{[^}]*animation:[^;}]*\\bui-pop-in\\b`), `${selector} opens with ui-pop-in`);
  }
  const body = keyframeBody(css, 'ui-pop-in');
  assert.match(body, /opacity:\s*0/, 'ui-pop-in fades');
  assert.match(body, /translateY\(6px\)/, 'ui-pop-in rises 6px');
});

test('list stagger covers the session rail, the results inventory and the explorer: max 8 items at 30 ms', async () => {
  const css = strip(await read('../src/styles/motion.css'));
  const surfaces = ['.session-list > ', '.rv-files ul > ', '.wb-explorer-group li'];
  for (const surface of surfaces) {
    const escaped = surface.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    assert.match(css, new RegExp(`${escaped}[^{]*\\{[^}]*animation:[^;}]*\\bui-list-in\\b`), `${surface} items enter with ui-list-in`);
    for (let item = 2; item <= 8; item += 1) {
      assert.match(
        css,
        new RegExp(`${escaped}:nth-child\\(${item}\\)[^{]*\\{[^}]*animation-delay:\\s*${(item - 1) * 30}ms`),
        `${surface} item ${item} waits ${(item - 1) * 30}ms`,
      );
    }
    assert.match(css, new RegExp(`${escaped}:nth-child\\(n\\+9\\)[^{]*\\{[^}]*animation:\\s*none`), `${surface} stops staggering after 8 items`);
  }
  const body = keyframeBody(css, 'ui-list-in');
  assert.match(body, /opacity:\s*0/, 'ui-list-in fades');
  assert.match(body, /translateY\(6px\)/, 'ui-list-in rises 6px');
});

test('approval card state change lives in chat-tools.css and never touches layout', async () => {
  const css = strip(await read('../src/styles/chat-tools.css'));
  assert.match(css, /\.approval-card\s*\{[^}]*transition:[^;}]*border-color/s, 'the card eases its border on state change');
  assert.match(css, /\.approval-card\[data-resolution="approved"\]/, 'approved has a state rule');
  assert.match(css, /\.approval-card\[data-resolution="rejected"\]/, 'rejected has a state rule');
});

test('run progress shimmer reuses an allowed loading keyframe and never animates layout', async () => {
  const [motion, controls] = await Promise.all([
    strip(await read('../src/styles/motion.css')),
    strip(await read('../src/styles/chat-tools.css')),
  ]);
  assert.doesNotMatch(motion, /@keyframes ui-skeleton-scan/, 'the shimmer reuses the control keyframe, it does not fork it');
  assert.match(motion, /\.run-progress-meter::after\s*\{[^}]*animation:[^;}]*\bui-skeleton-scan\b/s, 'the meter carries the shimmer');
  assert.match(motion, /\[data-inflight="true"\][^{]*\.run-progress-meter::after/, 'the shimmer only runs while progress is in flight');
});

test('no width/height/top/left transitions in touched files except two documented pre-existing lines', async () => {
  const allow = [
    '.panel-resizer span { transition: height var(--d-ui) var(--ease-ui), width var(--d-ui) var(--ease-ui), opacity var(--d-ui) var(--ease-ui), background var(--d-ui) var(--ease-ui); }',
    'html[data-motion="full"] .approval-countdown > span { transition: width 1s steps(10, end); }',
  ];
  for (const file of TOUCHED) {
    const css = strip(await read(file));
    for (const line of allow) {
      if (file === '../src/styles/motion.css' && line.includes('.panel-resizer')) {
        assert.ok(css.includes(line), 'the pre-existing sash exception is still exactly that line');
      }
      if (file === '../src/styles/chat-tools.css' && line.includes('.approval-countdown')) {
        assert.ok(css.includes(line), 'the pre-existing countdown exception is still exactly that line');
      }
    }
    const scrubbed = allow.reduce((text, line) => text.split(line).join(''), css);
    for (const m of scrubbed.matchAll(/transition\s*:\s*([^;]+);/g)) {
      assert.doesNotMatch(m[1], /\b(width|height|top|left)\b/, `${file}: transition animates layout: ${m[1].trim()}`);
    }
  }
});

test('every new keyframes animates transform/opacity only and is neutralised under prefers-reduced-motion', async () => {
  const css = strip(await read('../src/styles/motion.css'));
  for (const name of NEW_KEYFRAMES) {
    const body = keyframeBody(css, name);
    assert.doesNotMatch(body, /\b(width|height|top|left|margin|padding)\b/, `@keyframes ${name} never moves layout`);
  }
  const reduceAt = css.indexOf('@media (prefers-reduced-motion: reduce)');
  assert.ok(reduceAt >= 0, 'motion.css has a reduced-motion block');
  const reduce = css.slice(reduceAt);
  assert.match(reduce, /animation:\s*none/, 'new entrances stop under reduced motion');
  assert.match(reduce, /transition:\s*none/, 'new indicator slides stop under reduced motion');
  for (const selector of ['.ui-popover', '.ui-menu', '.session-list', '.rv-files', '.wb-explorer-group', '.ui-tab-indicator', '.ui-segmented-indicator']) {
    assert.ok(reduce.includes(selector), `reduced motion covers ${selector}`);
  }
});
