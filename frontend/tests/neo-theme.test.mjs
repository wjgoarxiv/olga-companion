import assert from 'node:assert/strict';
import { existsSync, readdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// The Terminalcore theme (owner brand woojin-go-terminalcore, static only).
// Static checks on tokens, ratios, motion presets, the pixel icon set and the
// chrome that carries them. Day = #e1e2e7 canvas, Night = #16161e canvas.
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function lum(hex) {
  const c = hex.replace('#', '');
  const v = [0, 2, 4].map((i) => {
    const x = parseInt(c.slice(i, i + 2), 16) / 255;
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}
const ratio = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);

function block(css, selector) {
  const start = css.indexOf(selector);
  assert.ok(start >= 0, `missing ${selector}`);
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}') { depth -= 1; if (depth === 0) return css.slice(open + 1, i); }
  }
  throw new Error(`unbalanced ${selector}`);
}
const hexes = (body) => Object.fromEntries([...body.matchAll(/--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\b/g)].map((m) => [m[1], m[2].toLowerCase()]));

async function themes() {
  const css = await read('../src/styles/base.css');
  return {
    css,
    light: hexes(block(css, ':root {')),
    lightAttr: hexes(block(css, ':root[data-theme="light"]')),
    dark: hexes(block(css, ':root[data-theme="dark"]')),
    osDark: hexes(block(css, ':root:not([data-theme="light"])')),
  };
}

test('Terminalcore role values, both themes (Day and Night pinned)', async () => {
  const t = await themes();
  const expected = {
    dark: { bg: '#16161e', panel: '#1a1b26', raised: '#1a1b26', ink: '#c0caf5', select: '#7aa2f7', 'on-select': '#16161e', accent: '#7aa2f7', 'accent-2': '#9ece6a', focus: '#7dcfff', pass: '#9ece6a', info: '#7dcfff', fail: '#f7768e', warn: '#e0af68' },
    light: { bg: '#e1e2e7', panel: '#eceef3', raised: '#eceef3', ink: '#1f2335', select: '#2459c9', 'on-select': '#fbfcff', accent: '#2459c9', 'accent-2': '#3d6b1f', focus: '#2459c9', pass: '#3d6b1f', info: '#006a8e', fail: '#c0174a', warn: '#7a5200' },
  };
  for (const [name, want] of Object.entries(expected.dark)) assert.equal(t.dark[name], want, `dark --${name}`);
  for (const [name, want] of Object.entries(expected.light)) {
    assert.equal(t.light[name], want, `light :root --${name}`);
    assert.equal(t.lightAttr[name], want, `light [data-theme] --${name}`);
  }
});

test('the old neo-brutal palette is gone from every stylesheet', async () => {
  const dir = new URL('../src/styles/', import.meta.url);
  for (const file of readdirSync(dir).filter((name) => name.endsWith('.css'))) {
    const css = await readFile(new URL(file, dir), 'utf8');
    assert.doesNotMatch(css, /#c8ff1a|#ff3d8b|#c4105e|#3b5200|#e8e6dd|#09090a|#f3f2eb|#0b0b0c/i, `${file} keeps no neo-brutal colour`);
  }
});

test('contrast: text 4.5:1, ink steps 10/8/5, non-text 3:1, both themes', async () => {
  const t = await themes();
  for (const [label, v] of [['light', t.light], ['dark', t.dark]]) {
    const surfaces = ['bg', 'panel', 'panel-2', 'raised'];
    for (const s of surfaces) {
      assert.ok(ratio(v.ink, v[s]) >= 10, `${label} ink on ${s}`);
      assert.ok(ratio(v['ink-2'], v[s]) >= 8, `${label} ink-2 on ${s}`);
      assert.ok(ratio(v.mute, v[s]) >= 5, `${label} mute on ${s}`);
      for (const role of ['accent', 'accent-2', 'signal', 'pass', 'warn', 'fail', 'info']) {
        assert.ok(ratio(v[role], v[s]) >= 4.5, `${label} ${role} text on ${s} >= 4.5 (got ${ratio(v[role], v[s]).toFixed(2)})`);
      }
      assert.ok(ratio(v.focus, v[s]) >= 3, `${label} focus ring on ${s} >= 3:1`);
      assert.ok(ratio(v.select, v[s]) >= 3, `${label} select fill on ${s} >= 3:1`);
      assert.ok(ratio(v.hairline, v[s]) >= 3, `${label} control border (hairline) on ${s} >= 3:1`);
      assert.ok(ratio(v.edge, v[s]) >= 3, `${label} compartment edge on ${s} >= 3:1`);
    }
    assert.ok(ratio(v['on-select'], v.select) >= 6, `${label} text on the select fill`);
    assert.ok(ratio(v['on-select-mute'], v.select) >= 4.5, `${label} secondary text on the select fill`);
    assert.ok(ratio(v['accent-ink'], v.accent) >= 4.5, `${label} text on the accent fill`);
    assert.ok(ratio(v['accent-2-ink'], v['accent-2']) >= 4.5, `${label} text on the green fill`);
    assert.ok(ratio(v['signal-ink'], v.signal) >= 4.5, `${label} text on the signal fill`);
    assert.ok(ratio(v['info-ink'], v.info) >= 4.5, `${label} text on the info fill`);
    assert.ok(ratio(v.accent, v['accent-soft']) >= 4.5, `${label} accent text on its soft fill`);
    assert.ok(ratio(v['on-bubble-user'], v['bubble-user']) >= 7, `${label} user bubble text on its wash`);
    for (const series of ['s1', 's2', 's3', 's4', 's5']) {
      assert.ok(ratio(v[series], v.film) >= 3, `${label} ${series} data line on the plot film >= 3:1`);
    }
  }
});

test('the OS-dark block carries the same dark roles as [data-theme="dark"]', async () => {
  const t = await themes();
  for (const name of ['bg', 'panel', 'ink', 'ink-2', 'mute', 'select', 'on-select', 'on-select-mute', 'accent', 'accent-2', 'accent-ink', 'hairline', 'edge', 'focus', 'pass', 'warn', 'fail', 'info', 's1', 's2']) {
    assert.equal(t.osDark[name], t.dark[name], `OS-dark --${name} equals dark --${name}`);
  }
});

test('hard edges: legacy radius tokens are square', async () => {
  const { css } = await themes();
  for (const token of ['--r-surface', '--r-input', '--r-pill']) {
    assert.match(css, new RegExp(`${token}:\\s*0\\b`), `${token} is 0`);
  }
});

test('fonts: Meslo LGS NF for body and mono, Pretendard for Korean and display, no CDN', async () => {
  const { css } = await themes();
  assert.match(css, /--font-ui:\s*"Meslo LGS NF"/);
  assert.match(css, /--font-mono:\s*"Meslo LGS NF"/);
  assert.match(css, /--font-display:\s*"Pretendard Variable"/);
  assert.match(css, /:root:lang\(ko\)\s*\{\s*--font-ui:\s*"Pretendard Variable"/, 'Korean body text sets in Pretendard');
  assert.match(css, /--track-label:\s*0\.08em/, 'labels track 0.08em');
  assert.doesNotMatch(css, /https?:\/\//, 'no remote font or asset');
  assert.match(css, /url\("\/fonts\/PretendardVariable\.woff2"\)/);
  assert.match(css, /url\("\/fonts\/MesloLGSNF-Regular\.woff2"\)/);
  assert.match(css, /url\("\/fonts\/MesloLGSNF-Bold\.woff2"\)/);
  for (const file of ['MesloLGSNF-Regular.woff2', 'MesloLGSNF-Bold.woff2', 'PretendardVariable.woff2', 'Meslo-LICENSE.txt', 'Pretendard-OFL.txt', 'NerdFonts-LICENSE.txt']) {
    assert.ok(existsSync(new URL(`../public/fonts/${file}`, import.meta.url)), `public/fonts/${file} ships with its licence`);
  }
  assert.ok(!existsSync(new URL('../public/fonts/MesloLGSNerdFontMono-Regular.ttf', import.meta.url)), 'the old 2.8 MB Meslo ttf is out of the app bundle');
  assert.ok(existsSync(new URL('../../assets/fonts/MesloLGSNerdFontMono-Regular.ttf', import.meta.url)), 'it lives in assets/fonts for the video and cover');
  assert.ok(existsSync(new URL('../../assets/fonts/NerdFonts-LICENSE.txt', import.meta.url)), 'with its licence');
  const [videoPkg, videoFonts, cover] = await Promise.all(['../../video/package.json', '../../video/src/fonts.ts', '../../assets/make_cover.py'].map((p) => read(p)));
  assert.match(videoPkg, /\.\.\/assets\/fonts\/MesloLGSNerdFontMono-Regular\.ttf/, 'the video fonts script copies from assets/fonts');
  assert.doesNotMatch(videoPkg, /frontend\/public\/fonts\/'\+f/, 'no stale frontend copy loop');
  assert.match(videoFonts, /fonts\/MesloLGSNerdFontMono-Regular\.ttf/);
  assert.match(cover, /Path\(__file__\)\.parent \/ "fonts" \/ "MesloLGSNerdFontMono-Regular\.ttf"/);
  assert.doesNotMatch(css, /Monument/i, 'Monument is never shipped');
});

test('motion presets: --mo/--mo-move/--fx with off|subtle|full, subtle by default', async () => {
  const { css } = await themes();
  for (const token of ['--mo', '--mo-move', '--fx']) assert.match(css, new RegExp(`${token}:`), `${token} is a token`);
  const root = block(css, ':root {');
  assert.match(root, /--mo:\s*\.7/, 'subtle is the default multiplier');
  assert.match(root, /--fx:\s*0/, 'effects are off by default');
  assert.match(block(css, 'html[data-motion="off"]'), /--mo:\s*0/);
  assert.match(block(css, 'html[data-motion="subtle"]'), /--mo:\s*\.7/);
  assert.match(block(css, 'html[data-motion="full"]'), /--fx:\s*1/);
  assert.match(css, /--d-ui:\s*calc\(120ms \* var\(--mo\)\)/);
  assert.match(css, /--d-enter:\s*calc\(240ms \* var\(--mo\)\)/);
  assert.match(css, /--d-exit:\s*calc\(100ms \* var\(--mo\)\)/);
  assert.match(css, /--d-snap:\s*calc\(80ms \* var\(--mo\)\)/);
  for (const token of ['--ease-ui', '--ease-enter', '--ease-exit', '--ease-snap', '--ease-out', '--ease-emphasized']) {
    assert.match(css, new RegExp(`${token}:\\s*steps\\(3, end\\)`), `${token} is stepped`);
  }
  assert.match(css, /@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*?:root:not\(\[data-motion\]\)/);
});

test('appearance: off|subtle|full, reduced-motion starts at off, legacy reduced reads as subtle', async () => {
  const src = await read('../src/appearance.ts');
  assert.match(src, /type ResolvedMotion = 'off' \| 'subtle' \| 'full'/);
  assert.match(src, /systemReduced \? 'off' : 'subtle'/, 'prefers-reduced-motion resolves to off, otherwise subtle');
  assert.match(src, /value === 'reduced'/, 'a stored legacy "reduced" choice is read as subtle');
  assert.match(src, /MOTION_KEY = 'olga-companion\.motion\.v1'/, 'persisted like ui-scale, same key family');
  const settings = await read('../src/SettingsView.tsx');
  assert.match(settings, /value: 'subtle'/);
  assert.doesNotMatch(settings, /value: 'reduced'/);
  const en = await read('../src/i18n/en.ts');
  const ko = await read('../src/i18n/ko.ts');
  assert.match(en, /'settings\.motionSubtle': 'Subtle'/);
  assert.match(ko, /'settings\.motionSubtle': '은은함'/);
});

test('PixelIcon: 12x12 rect-only symbols, currentColor, crispEdges, aria-hidden by default', async () => {
  const src = await read('../src/ui/PixelIcon.tsx');
  assert.match(src, /viewBox="0 0 12 12"/);
  assert.match(src, /shapeRendering="crispEdges"/);
  assert.match(src, /fill="currentColor"/);
  assert.match(src, /aria-hidden/);
  assert.doesNotMatch(src, /<path|<circle|<polygon|<image/, 'rects only');
  for (const name of ['case', 'edit', 'validate', 'run', 'results', 'chat', 'settings', 'fluid', 'warning', 'ok', 'folder', 'file', 'graph', 'export', 'collapse', 'grip']) {
    assert.match(src, new RegExp(`\\b${name}:\\s*\\[`), `icon ${name} is drawn`);
  }
});

test('chrome: pixel icons on the rail, step bar, explorer; chevron steps; index chips', async () => {
  const [rail, step, explorer, dock, panel, centre, wb, sim] = await Promise.all([
    read('../src/shell/ActivityBar.tsx'),
    read('../src/shell/StepBar.tsx'),
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/shell/ChatDock.tsx'),
    read('../src/shell/BottomPanel.tsx'),
    read('../src/shell/CentreViews.tsx'),
    read('../src/styles/workbench.css'),
    read('../src/styles/simulation-guide.css'),
  ]);
  assert.match(rail, /PixelIcon/);
  assert.doesNotMatch(rail, /Icon3D/, 'the rail uses the pixel set, not 3D renders');
  assert.match(step, /PixelIcon/);
  assert.match(explorer, /PixelIcon/);
  for (const [label, source, chip] of [['explorer', explorer, '01'], ['centre', centre, '02'], ['dock', dock, '03'], ['bottom panel', panel, '04']]) {
    assert.match(source, new RegExp(`PaneIndex[^>]*index="${chip}"|wb-pane-idx[^>]*>\\s*${chip}`), `${label} carries index chip ${chip}`);
  }
  assert.match(sim, /\.step-cell\s*\{[^}]*clip-path:\s*polygon/s, 'chevron step cells');
  assert.match(wb, /\.wb-activity-indicator\s*\{[^}]*background:\s*var\(--select\)/s, 'the active rail item is a solid select block');
  assert.match(wb, /--ab-w:\s*96px/, 'the labelled rail is 96 px wide');
  assert.match(wb, /\.wb-explorer\s*\{[^}]*border-right:\s*2px solid var\(--edge\)/s, 'flush 2 px compartments');
});

test('no motion on approval controls beyond focus and hover (new rules)', async () => {
  const css = await read('../src/styles/base.css');
  const motion = await read('../src/styles/motion.css');
  assert.doesNotMatch(css + motion, /\.approval[^{]*\{[^}]*(animation|transition)\s*:[^}]*(--mo|translate|scale)/s, 'neo motion never targets the approval card');
  assert.match(motion, /:not\(\.approval-card[^)]*\)|:where\(\.approval-card/, 'the generic hover lift excludes approval controls');
  assert.match(motion, /:not\(\.approve\)/, 'approve is outside the hover lift');
  assert.match(motion, /:not\(\.ui-button-primary\)/, 'primary buttons are outside the hover lift');
  assert.match(motion, /:not\(\.wb-btn-primary\)/, 'workbench primary buttons are outside the hover lift');
  assert.match(motion, /:not\(\[data-busy\]\)/, 'busy controls are outside the hover lift');
  assert.match(motion, /:not\(\.run-go\)/, 'run-go has no hover lift');
});
