import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

// W3-L1 paint/QA RED-first suite. Fails on HEAD (dashed disabled slabs,
// 0.34-opacity sash, unstyled coachmark), passes after the paint lands.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const css = (p) => fs.readFileSync(path.join(root, 'src', 'styles', p), 'utf8');
const src = (p) => fs.readFileSync(path.join(root, 'src', p), 'utf8');

function lum(hex) {
  const c = hex.replace('#', '');
  const v = [0, 2, 4].map((i) => {
    const x = parseInt(c.substr(i, 2), 16) / 255;
    return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}
function ratio(a, b) {
  return (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
}
function blend(fg, bg, alpha) {
  const p = (h) => [0, 2, 4].map((i) => parseInt(h.replace('#', '').substr(i, 2), 16));
  const f = p(fg), b = p(bg);
  const m = f.map((v, i) => Math.round(v * alpha + b[i] * (1 - alpha)));
  return '#' + m.map((v) => v.toString(16).padStart(2, '0')).join('');
}
// role -> hex per theme, parsed from base.css :root (light) and the dark override
function themeRoles() {
  const base = css('base.css');
  const lightBlock = base.slice(0, base.indexOf('@media'));
  const darkBlock = base.slice(base.indexOf('@media'));
  const read = (block, name) => {
    const m = block.match(new RegExp('--' + name + ':\\s*(#[0-9a-fA-F]{6})'));
    assert.ok(m, `role --${name} must exist`);
    return m[1];
  };
  const out = {};
  for (const theme of ['light', 'dark']) {
    const block = theme === 'light' ? lightBlock : darkBlock;
    out[theme] = {
      raised: read(block, 'raised'),
      panel: read(block, 'panel'),
      mute: read(block, 'mute'),
    };
  }
  return out;
}

test('W3-L1 M3: one shared disabled triple, solid, opaque, ≥4.5:1 both themes', () => {
  const controls = css('controls.css');
  for (const token of ['--btn-disabled-bg', '--btn-disabled-text', '--btn-disabled-border']) {
    assert.match(controls, new RegExp(token + '\\s*:'));
  }
  const btnRule = controls.match(/\.ui-button:disabled\s*\{[^}]*\}/);
  assert.ok(btnRule, '.ui-button:disabled rule must exist');
  assert.ok(!/dashed/.test(btnRule[0]), 'disabled must not use a dashed border');
  assert.ok(!/opacity\s*:\s*0\./.test(btnRule[0]), 'disabled must not fade the whole element');
  assert.match(btnRule[0], /var\(--btn-disabled-bg\)/);
  assert.match(btnRule[0], /var\(--btn-disabled-text\)/);
  assert.match(btnRule[0], /var\(--btn-disabled-border\)/);
  const roles = themeRoles();
  for (const theme of ['light', 'dark']) {
    const r = ratio(roles[theme].mute, roles[theme].raised);
    assert.ok(r >= 4.5, `disabled label (mute on raised) must reach 4.5:1 in ${theme}, got ${r.toFixed(2)}`);
  }
});

test('W3-L1 M6 FIX: .wb-btn:disabled reuses the shared triple, no fork', () => {
  const controls = css('controls.css');
  const wbRule = controls.match(/\.wb-btn:disabled\s*\{[^}]*\}/);
  assert.ok(wbRule, '.wb-btn:disabled must be defined alongside the triple');
  assert.ok(!/dashed/.test(wbRule[0]), '.wb-btn:disabled must not use a dashed border');
  assert.match(wbRule[0], /var\(--btn-disabled-bg\)/);
  assert.match(wbRule[0], /var\(--btn-disabled-text\)/);
  const settings = css('settings.css');
  for (const sel of ['.update-actions button:disabled', '.update-actions .update-go:disabled']) {
    const rule = settings.match(new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{[^}]*\\}'));
    assert.ok(rule, `${sel} must exist`);
    assert.ok(!/dashed/.test(rule[0]), `${sel} must not use a dashed border`);
    assert.match(rule[0], /var\(--btn-disabled-(bg|text|border)\)/);
  }
});

test('W3-L1 M2: sash rest reaches 3:1 in both themes, rest opacity ≥0.6', () => {
  const panels = css('resizable-panels.css');
  assert.match(panels, /--sash-rest\s*:/);
  const restRule = panels.match(/\.panel-resizer span\s*\{[^}]*opacity\s*:\s*([\d.]+)/);
  assert.ok(restRule, 'rest grip opacity must be declared');
  assert.ok(Number(restRule[1]) >= 0.6, `rest opacity must be ≥0.6, got ${restRule[1]}`);
  const roles = themeRoles();
  for (const theme of ['light', 'dark']) {
    const r = ratio(blend(roles[theme].mute, roles[theme].panel, 0.7), roles[theme].panel);
    assert.ok(r >= 3.0, `sash rest (mute@0.7 over ${theme} panel) must reach 3:1, got ${r.toFixed(2)}`);
  }
  assert.match(panels, /\.panel-resizer:(hover|focus-visible|active) span[^{]*\{[^}]*opacity\s*:\s*1/);
  assert.match(panels, /\.panel-resizer:(hover|focus-visible|active) span[^{]*\{[^}]*height\s*:\s*64px/);
});

test('W3-L1: coachmark is a compact dismissible callout card, 12px floor', () => {
  const coach = src('shell/ResizeCoachmark.tsx');
  assert.match(coach, /lucide-react/);
  assert.match(coach, /resize\.shortcutsTitle/);
  assert.match(coach, /<Kbd/);
  assert.match(coach, /shell\.close/);
  assert.match(coach, /data-testid="resize-coachmark"/);
  assert.ok(!coach.includes('autoFocus') && !coach.includes('.focus()'));
  const panels = css('resizable-panels.css');
  const card = panels.match(/\.resize-coachmark\s*\{[^}]*\}/);
  assert.ok(card, '.resize-coachmark card style must exist');
  assert.ok(!/font-size\s*:\s*(1[01]|[0-9])px/.test(card[0]), 'coachmark text must keep the 12px floor');
});

test('W3-L1: no sub-12px font-size anywhere in styles at 100 % scale', () => {
  const dir = path.join(root, 'src', 'styles');
  const base = css('base.css');
  const tokens = {};
  for (const m of base.matchAll(/--(fs-[\w]+):\s*calc\((\d+(?:\.\d+)?)px \* var\(--ui-scale\)\)/g)) tokens[m[1]] = Number(m[2]);
  assert.ok(Object.keys(tokens).length >= 6, 'the scaled type tokens exist');
  for (const file of fs.readdirSync(dir).filter((f) => f.endsWith('.css'))) {
    const text = fs.readFileSync(path.join(dir, file), 'utf8');
    for (const m of text.matchAll(/font-size\s*:\s*([^;}]+)/g)) {
      const value = m[1].replace(/\s*!important/, '').trim();
      const plain = value.match(/^(\d+(?:\.\d+)?)px$/);
      const scaled = value.match(/^calc\(\s*(\d+(?:\.\d+)?)px\s*\*\s*var\(--ui-scale\)\s*\)$/);
      const token = value.match(/^var\(--(fs-[\w]+)\)$/);
      const px = plain ? Number(plain[1]) : scaled ? Number(scaled[1]) : token ? tokens[token[1]] : null;
      if (px !== null) assert.ok(px >= 12, `${file}: font-size ${value} breaks the 12px floor at 100 %`);
    }
  }
  assert.ok(tokens['fs-xs'] >= 12, 'type scale floor must stay ≥12px');
});
