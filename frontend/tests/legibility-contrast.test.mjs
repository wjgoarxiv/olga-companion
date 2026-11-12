import assert from 'node:assert/strict';
import { readdirSync, readFile } from 'node:fs';
import { readFile as readAsyncFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readAsyncFile(new URL(path, import.meta.url), 'utf8');

function hexToRgb(hex) {
  const clean = hex.replace('#', '');
  const full = clean.length === 3 ? clean.split('').map((c) => c + c).join('') : clean;
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
}

function luminance([r, g, b]) {
  const channel = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(fg, bg) {
  const a = luminance(hexToRgb(fg));
  const b = luminance(hexToRgb(bg));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function blockVars(css, startMarker) {
  const start = css.indexOf(startMarker);
  assert.ok(start >= 0, `missing block ${startMarker}`);
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) {
        const body = css.slice(open + 1, i);
        const vars = {};
        for (const match of body.matchAll(/--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6}|\d+(?:\.\d+)?px|calc\(\d+(?:\.\d+)?px \* var\(--ui-scale\)\))/g)) {
          // Scaled tokens report their 100 % pixel value.
          vars[match[1]] = match[2].startsWith('calc(') ? `${match[2].match(/\d+(?:\.\d+)?/)[0]}px` : match[2];
        }
        return vars;
      }
    }
  }
  throw new Error(`unbalanced block ${startMarker}`);
}


// Base px of a font-size value at 100 % scale: plain px, calc(N px * scale),
// a calc(clamp(min, ...)) wrapper, or a --fs-* token read from base.css.
function basePx(value, tokens) {
  const v = value.trim();
  let m = v.match(/^(\d+(?:\.\d+)?)px$/);
  if (m) return Number(m[1]);
  m = v.match(/^calc\(\s*(\d+(?:\.\d+)?)px\s*\*\s*var\(--ui-scale\)\s*\)$/);
  if (m) return Number(m[1]);
  m = v.match(/^calc\(\s*clamp\(\s*(\d+(?:\.\d+)?)px/);
  if (m) return Number(m[1]);
  m = v.match(/^var\(--(fs-[\w]+)\)$/);
  if (m && tokens[m[1]] !== undefined) return tokens[m[1]];
  return null;
}

// Legibility revision (Terminalcore): body/UI text is the Tokyo Night ink in
// both themes (blue and green are accents only), every visible glyph is
// >= 12 px, and the ink steps clear 10:1 / 8:1 / 5:1 against every surface
// (the kit palette tops out at 10.59 / 8.10 / 5.00 on Night panels).
test('ink steps are the Terminalcore inks and clear 10:1, 8:1 and 5:1 on every surface', async () => {
  const css = await read('../src/styles/base.css');
  const light = blockVars(css, ':root');
  const dark = blockVars(css, ':root[data-theme="dark"]');
  const pinned = {
    light: { ink: '#1f2335', 'ink-2': '#343b58', mute: '#4c5585' },
    dark: { ink: '#c0caf5', 'ink-2': '#a9b1d6', mute: '#8089b3' },
  };
  for (const [label, vars] of [['light', light], ['dark', dark]]) {
    for (const surface of ['bg', 'panel', 'raised']) {
      assert.ok(contrast(vars['ink'], vars[surface]) >= 10, `${label} ink on ${surface} >= 10:1`);
      assert.ok(contrast(vars['ink-2'], vars[surface]) >= 8, `${label} ink-2 on ${surface} >= 8:1`);
      assert.ok(contrast(vars['mute'], vars[surface]) >= 5, `${label} mute on ${surface} >= 5:1`);
    }
    for (const name of ['ink', 'ink-2', 'mute']) {
      assert.equal(vars[name].toLowerCase(), pinned[label][name], `${label} --${name} is the Terminalcore value`);
      const [r, g, b] = hexToRgb(vars[name]);
      assert.ok(b >= r, `${label} ${name} keeps the cool Tokyo Night tint`);
    }
  }
});

test('the type scale has no step below 12 px', async () => {
  const css = await read('../src/styles/base.css');
  const light = blockVars(css, ':root');
  const steps = Object.entries(light).filter(([name]) => name.startsWith('fs-'));
  assert.ok(steps.length >= 6, 'the scale keeps its steps');
  for (const [name, value] of steps) {
    const px = Number(value.replace('px', ''));
    assert.ok(px >= 12, `type step --${name} is >= 12 px`);
  }
});

test('no stylesheet sets type below the 12 px floor', async () => {
  const dir = new URL('../src/styles/', import.meta.url);
  const offenders = [];
  const tokens = Object.fromEntries(Object.entries(blockVars(await read('../src/styles/base.css'), ':root'))
    .filter(([name]) => name.startsWith('fs-')).map(([name, value]) => [name, Number(value.replace('px', ''))]));
  for (const file of readdirSync(dir)) {
    if (!file.endsWith('.css')) continue;
    const css = await read(`../src/styles/${file}`);
    for (const match of css.matchAll(/font-size\s*:\s*([^;}]+)/g)) {
      const px = basePx(match[1].replace(/\s*!important/, ''), tokens);
      if (px !== null && px < 12) offenders.push(`${file}: ${match[0]}`);
    }
  }
  assert.deepEqual(offenders, [], 'every visible glyph sets >= 12 px');
});

test('the OS-dark media block mirrors the explicit dark roles', async () => {
  const css = await read('../src/styles/base.css');
  const mediaStart = css.indexOf('@media (prefers-color-scheme: dark)');
  assert.ok(mediaStart >= 0, 'the OS-dark fallback block exists');
  const dark = blockVars(css, ':root[data-theme="dark"]');
  const mediaBody = css.slice(mediaStart);
  for (const name of ['ink', 'ink-2', 'mute', 'select', 'on-select', 'signal-ink', 'info-ink', 'pass']) {
    const match = mediaBody.match(new RegExp(`--${name}\\s*:\\s*(#[0-9a-fA-F]{3,6})`));
    assert.ok(match, `media block sets --${name}`);
    assert.equal(match[1].toLowerCase(), dark[name].toLowerCase(), `media --${name} matches the dark role`);
  }
});

test('density and scale blocks override no colour role, so contrast is identical', async () => {
  const css = await read('../src/styles/base.css');
  const comfortable = css.match(/\[data-density="comfortable"\]\s*\{([^}]*)\}/s);
  assert.ok(comfortable, 'the comfortable block exists');
  const blocks = [comfortable[1], ...[...css.matchAll(/\[data-ui-scale="\d+"\]\s*\{([^}]*)\}/g)].map((m) => m[1])];
  assert.ok(blocks.length === 7, 'comfortable plus the six scale steps');
  for (const block of blocks) {
    const names = [...block.matchAll(/--([\w-]+)\s*:/g)].map((m) => m[1]);
    assert.ok(names.length > 0, 'each block overrides something');
    for (const name of names) {
      assert.ok(
        /^(tgt|ctl-h|sp-|r-|d-|fs-|sb-|ui-scale)/.test(name),
        `density and scale only touch spacing/target/scale tokens, never colour: --${name}`,
      );
    }
  }
});

/* Todo 15 live audit: the only sub-12px nodes were markdown table code
 * (0.92em inside 13px tables = 11.96px). Table code must clear the 12px
 * floor everywhere. */
test('markdown table code clears the 12px floor', async () => {
  const css = await read('../src/styles/chat-messages.css');
  const rule = css.match(/\.md\s+(td|th)\s+code[^{]*\{[^}]*font-size:\s*([^;}]+)/s);
  assert.ok(rule, 'table code sets a font size');
  const base = await read('../src/styles/base.css');
  const tokens = Object.fromEntries(Object.entries(blockVars(base, ':root'))
    .filter(([name]) => name.startsWith('fs-')).map(([name, value]) => [name, Number(value.replace('px', ''))]));
  const px = basePx(rule[2], tokens);
  assert.ok(px !== null && px >= 12, `table code pins >= 12px at 100 % (got ${rule[2]})`);
});

test('text on filled accents clears 4.5:1 in both themes', async () => {
  const css = await read('../src/styles/base.css');
  const light = blockVars(css, ':root');
  const dark = blockVars(css, ':root[data-theme="dark"]');
  for (const [label, vars] of [['light', light], ['dark', dark]]) {
    assert.ok(contrast(vars['accent-ink'], vars['accent']) >= 4.5, `${label} text on accent fill >= 4.5:1`);
    assert.ok(contrast(vars['signal-ink'], vars['signal']) >= 4.5, `${label} text on signal fill >= 4.5:1`);
    assert.ok(contrast(vars['info-ink'], vars['info']) >= 4.5, `${label} text on info fill >= 4.5:1`);
    assert.ok(contrast(vars['on-ink-body'], vars['accent']) >= 4.5, `${label} body copy on accent fill >= 4.5:1`);
  }
});
