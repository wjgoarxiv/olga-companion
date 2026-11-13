import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// Terminalcore (owner brand woojin-go-terminalcore), static only: square
// corners, no gradients, no blur, no glow or soft shadow, stepped easing, no
// RGB-offset, no scan sweep. The only gradient allowed is the kit's hard-stop
// plot grid defined once as --plot-grid in base.css.
const dir = new URL('../src/styles/', import.meta.url);
const files = readdirSync(dir).filter((name) => name.endsWith('.css')).sort();
const read = async (name) => readFile(new URL(name, dir), 'utf8');
const strip = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const declarations = (css) => [...strip(css).matchAll(/([\w-]+)\s*:\s*([^;{}]+)(?=[;}])/g)].map((m) => ({ prop: m[1], value: m[2].trim() }));

test('the stylesheet set is the one this theme was swept over', () => {
  assert.ok(files.length >= 20, `found ${files.length} stylesheets`);
});

test('no stylesheet has a non-zero border-radius', async () => {
  const square = /^(?:0|0px|inherit|var\(--r-(?:s|m|surface|input|pill)\))(?:\s+(?:0|0px|var\(--r-(?:s|m|surface|input|pill)\)))*$/;
  for (const file of files) {
    for (const { prop, value } of declarations(await read(file))) {
      if (!/radius/.test(prop)) continue;
      assert.match(value, square, `${file}: ${prop}: ${value}`);
    }
  }
});

test('every radius token resolves to 0', async () => {
  const base = await read('base.css');
  for (const token of ['--r-s', '--r-m', '--r-surface', '--r-input', '--r-pill']) {
    assert.match(base, new RegExp(`${token}:\\s*0;`), `${token} is 0`);
  }
});

test('no stylesheet has a gradient other than the kit plot grid token', async () => {
  for (const file of files) {
    const css = strip(await read(file));
    const hits = [...css.matchAll(/(?:repeating-)?(?:linear|radial|conic)-gradient\(/g)].length;
    if (file === 'base.css') {
      const grid = css.match(/--plot-grid:\s*([^;]+);/);
      assert.ok(grid, 'base.css defines --plot-grid');
      const inGrid = [...grid[1].matchAll(/linear-gradient\(/g)].length;
      assert.equal(inGrid, 4, 'the plot grid is four hard-stop 1 px line layers (32 px minors, 160 px majors)');
      assert.equal(hits, inGrid, 'base.css has no gradient outside --plot-grid');
      assert.doesNotMatch(grid[1], /\d%\s*,\s*var|transparent\s+\d+%/, 'every grid stop is a hard 1 px stop');
    } else {
      assert.equal(hits, 0, `${file} has no gradient`);
    }
  }
});

test('no stylesheet has a blur, a backdrop filter or a glow', async () => {
  for (const file of files) {
    const css = strip(await read(file));
    assert.doesNotMatch(css, /blur\(/, `${file} has no blur`);
    assert.doesNotMatch(css, /backdrop-filter/, `${file} has no backdrop filter`);
    assert.doesNotMatch(css, /drop-shadow\(/, `${file} has no drop shadow`);
    assert.doesNotMatch(css, /text-shadow\s*:\s*(?!none)/, `${file} has no text shadow (no RGB offset)`);
    for (const { prop, value } of declarations(css)) {
      if (!/shadow/.test(prop) || value === 'none') continue;
      // Hard rings and insets only: x y 0 [spread] colour. Blur radius must be 0.
      for (const layer of value.split(/,(?![^()]*\))/)) {
        const bare = layer.replace(/var\([^)]*\)|rgba?\([^)]*\)|color-mix\([^)]*\)|#[0-9a-f]+|inset/gi, ' ').trim();
        const nums = bare.split(/\s+/).filter(Boolean);
        if (nums.length >= 3) assert.match(nums[2], /^0(px)?$/, `${file}: ${prop}: ${value} has a blurred layer`);
      }
    }
  }
});

test('easing is stepped: no cubic-bezier or smooth timing keyword in any stylesheet', async () => {
  for (const file of files) {
    for (const { prop, value } of declarations(await read(file))) {
      if (!/^(transition|animation)/.test(prop)) continue;
      const literal = value.replace(/var\([^)]*\)/g, ' ');
      assert.doesNotMatch(literal, /cubic-bezier|\b(?:ease|ease-in|ease-out|ease-in-out|linear)\b/, `${file}: ${prop}: ${value}`);
    }
  }
});

test('no hard-coded colour in any stylesheet outside base.css; tokens only', async () => {
  for (const file of files.filter((name) => name !== 'base.css')) {
    const css = strip(await read(file));
    assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/, `${file} has no hex literal`);
    assert.doesNotMatch(css, /rgba?\(\s*\d/, `${file} has no rgb literal`);
  }
});

// Explicit allow-list: the mark keeps Night token fallbacks (`var(--accent, #7aa2f7)`) for the case where a token is unset.
const HEX_ALLOWED = new Set(['BrandMark.tsx']);
test('colour in component code comes from tokens: no hex literal in any src ts, tsx or mjs file', async () => {
  const src = new URL('../src/', import.meta.url);
  const scanned = readdirSync(src, { recursive: true }).filter((name) => /\.(tsx?|mjs)$/.test(name));
  assert.ok(scanned.length > 100, `scanned ${scanned.length} source files`);
  for (const file of scanned) {
    if (HEX_ALLOWED.has(file.split(/[\\/]/).pop())) continue;
    const text = (await readFile(new URL(file, src), 'utf8')).replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '');
    assert.doesNotMatch(text, /#[0-9a-fA-F]{3,8}\b/, `${file} has no hex colour literal`);
  }
  const brand = await readFile(new URL('../src/BrandMark.tsx', import.meta.url), 'utf8');
  for (const m of brand.matchAll(/#[0-9a-fA-F]{3,8}\b/g)) assert.match(m[0], /^#(7aa2f7|9ece6a)$/i, 'BrandMark hex literals are only the Night token fallbacks');
  for (const [file, name] of [['RunSweepStatus.tsx', 'SWEEP_OVERLAY_COLORS'], ['useResultSeriesOverlay.ts', 'OVERLAY_COLORS']]) {
    const text = await readFile(new URL(`../src/${file}`, import.meta.url), 'utf8');
    assert.match(text, new RegExp(`${name} = \\['var\\(--s1\\)', 'var\\(--s2\\)', 'var\\(--s3\\)', 'var\\(--s4\\)', 'var\\(--s5\\)'\\]`), `${file} reads the series tokens`);
  }
});

test('the Settings toggle keeps data-theme as the override and the OS scheme is the default', async () => {
  const base = await read('base.css');
  const appearance = await readFile(new URL('../src/appearance.ts', import.meta.url), 'utf8');
  assert.match(appearance, /loadTheme\(\)[^]*?\?\? 'system'/, 'the stored default is "system"');
  assert.match(base, /@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)/, 'Night follows the OS unless Day is forced');
  assert.match(base, /:root\[data-theme="light"\]/);
  assert.match(base, /:root\[data-theme="dark"\]/);
});

test('type: labels track 0.08em and no label is smaller than the 12 px floor', async () => {
  for (const file of files) {
    const css = strip(await read(file));
    for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!/text-transform:\s*uppercase/.test(m[2]) || !/letter-spacing/.test(m[2])) continue;
      assert.doesNotMatch(m[2], /letter-spacing:\s*0?\.04em/, `${file}: ${m[1].trim()} tracks labels with the 0.04em of the old theme`);
    }
  }
  const base = await read('base.css');
  assert.match(base, /--fs-xs:\s*calc\(12px/, 'the 12 px floor is kept');
});

test('inverse title bars: the pane header is an ink bar with on-ink text and a focus ring that holds 3:1 on it', async () => {
  const css = await read('workbench.css');
  const base = await read('base.css');
  assert.match(css, /\.wb-pane-head\s*\{[^}]*background:\s*var\(--ink\)[^}]*color:\s*var\(--on-ink-body\)/s, 'the pane header is the inverse title bar');
  assert.match(css, /\.wb-pane-head :focus-visible\s*\{\s*outline-color:\s*var\(--on-ink-body\)/, 'focus rings on the bar read the bar text colour');
  const lum = (hex) => {
    const c = hex.replace('#', '');
    const v = [0, 2, 4].map((i) => { const x = parseInt(c.slice(i, i + 2), 16) / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  };
  const ratio = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
  const pick = (name, from) => base.slice(base.indexOf(from)).match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))[1];
  for (const [label, from] of [['light', ':root {'], ['dark', ':root[data-theme="dark"]']]) {
    const ink = pick('ink', from);
    assert.ok(ratio(pick('on-ink-body', from), ink) >= 10, `${label} bar text on the ink bar >= 10:1`);
    assert.ok(ratio(pick('on-ink-mute', from), ink) >= 4.5, `${label} muted bar text on the ink bar >= 4.5:1`);
  }
});

test('motion follow-up: the Off/Subtle/Full setting still works and Full has no flicker, blink, strobe, glitch or decoding', async () => {
  const appearance = await readFile(new URL('../src/appearance.ts', import.meta.url), 'utf8');
  assert.match(appearance, /type MotionChoice = 'system' \| 'off' \| 'subtle' \| 'full'/, 'the setting is kept');
  assert.match(appearance, /export function motionAllowsFull/, 'Full is still a level');
  const all = (await Promise.all(files.map(read))).map(strip).join('\n');
  for (const name of ['neo-glitch', 'neo-scan', 'neo-pulse', 'neo-flick', 'strobe-stamp', 'pane-title-glitch', 'wb-beat', 'wb-poweron', 'topo-pulse', 'topo-scan', 'topo-flow', 'activity-loader-breathe']) {
    assert.doesNotMatch(all, new RegExp(`${name}\\b`), `${name} is gone`);
  }
  for (const m of all.matchAll(/@keyframes\s+([\w-]+)\s*\{((?:[^{}]|\{[^{}]*\})*)\}/g)) {
    const opacities = [...m[2].matchAll(/opacity:\s*([\d.]+)/g)].map((o) => Number(o[1]));
    const blinks = opacities.some((v, i) => i >= 2 && ((opacities[i - 2] > opacities[i - 1] && opacities[i - 1] < v) || (opacities[i - 2] < opacities[i - 1] && opacities[i - 1] > v)));
    assert.ok(!blinks, `@keyframes ${m[1]} does not blink (opacity goes up and down)`);
  }
  const src = new URL('../src/', import.meta.url);
  for (const file of readdirSync(src, { recursive: true }).filter((name) => /\.(tsx|ts|mjs)$/.test(name))) {
    const text = await readFile(new URL(file, src), 'utf8');
    assert.doesNotMatch(text, /ScrambleText|scrambleFrame|scramble\.mjs/, `${file} does not decode text`);
  }
});

// Loops are allowed only for real loading states, each stepped (steps(3, end) via the token or literally) and still under reduced motion.
const INFINITE_ALLOWED = ['pixel-loader', 'ui-skeleton-scan', 'update-indeterminate'];
test('only the real loading indicators may loop, and each is stepped and still under reduced motion', async () => {
  const base = strip(await read('base.css'));
  assert.match(base, /html\[data-motion="off"\] \*[^{]*\{[^}]*animation:\s*none\s*!important/s, 'Off cancels every animation');
  assert.match(base, /:root:not\(\[data-motion\]\) \*[^{]*\{[^}]*animation:\s*none\s*!important/s, 'OS reduced motion cancels every animation');
  for (const file of files) {
    for (const { prop, value } of declarations(await read(file))) {
      if (prop !== 'animation' || !/\binfinite\b/.test(value)) continue;
      const name = INFINITE_ALLOWED.find((n) => value.includes(n));
      assert.ok(name, `${file}: "${value}" loops but is not an allowed loading indicator`);
      assert.match(value, /steps\(\s*3\s*,\s*end\s*\)|var\(--ease-(?:out|emphasized|ui)\)/, `${file}: ${name} is stepped`);
    }
  }
});

test('the still labels: the topology scanner is a still rule and edges are plain lines', async () => {
  const css = strip(await read('workbench.css'));
  assert.doesNotMatch(css, /topo-flow|topo-scan\b|stroke-dasharray:\s*5 4/, 'no marching edges and no sweeping scanner');
  assert.match(css, /\.topo-scanner\s*\{[^}]*height:\s*2px/s, 'the scanning cue is a still 2 px rule');
});

test('no dead --scan token remains', async () => {
  for (const file of files) assert.doesNotMatch(await read(file), /--scan\b/, `${file} has no --scan`);
});

test('wordmark mark renders at an integer multiple of its 16-unit grid', async () => {
  // The smooth vector mark needs no pixel alignment; the 16 px box keeps the
  // wordmark geometry unchanged.
  const css = strip(await read('workbench.css'));
  const size = css.match(/\.wordmark-mark\s*\{[^}]*width:\s*(\d+)px[^}]*height:\s*(\d+)px/s);
  assert.ok(size, '.wordmark-mark has a px size');
  assert.equal(size[1], size[2]);
  assert.equal(Number(size[1]) % 16, 0, 'a multiple of 16, matching the mark viewBox');
});

test('every text field with a focus rule keeps a visible focus ring', async () => {
  const css = strip(await read('results.css'));
  assert.doesNotMatch(css, /\.rv-filter:focus\s*\{[^}]*outline:\s*none/, 'no outline-removing focus rule on the variable filter');
  assert.match(css, /\.rv-filter:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--focus\)/, 'a visible 2 px ring');
});
