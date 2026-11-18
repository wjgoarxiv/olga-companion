import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

// M12 panel-default-height contract (assert-only lane W1-L4, R-r2 READY).
// Live HEAD measurement (P1 Round 1, restored live app, Problems tab with
// findings, previously-dragged stored height): open tabpanel 449px tall for
// what should be a compact one-line panel. Code default is 168
// (BottomPanel defaultHeight) — the gap this file pins is that nothing
// applies the compact default before first paint, so first paint sizes to
// content. No source change in this lane; the RED test below turns green
// when the owning (spacing-fix) lane lands a declarative default.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const bottomPanel = fs.readFileSync(path.join(root, 'src', 'shell', 'BottomPanel.tsx'), 'utf8');
const heightResizer = fs.readFileSync(path.join(root, 'src', 'shell', 'HeightResizer.tsx'), 'utf8');
const workbenchCss = fs.readFileSync(path.join(root, 'src', 'styles', 'workbench.css'), 'utf8');
const ko = fs.readFileSync(path.join(root, 'src', 'i18n', 'ko.ts'), 'utf8');
const en = fs.readFileSync(path.join(root, 'src', 'i18n', 'en.ts'), 'utf8');

test('M12: panel code default sits inside the compact 160-180px band', () => {
  const m = bottomPanel.match(/defaultHeight=\{(\d+)\}/);
  assert.ok(m, 'BottomPanel must pass an explicit defaultHeight to HeightResizer');
  const def = Number(m[1]);
  assert.ok(def >= 160 && def <= 180, `defaultHeight must be within 160-180px, got ${def}`);
});

test('M12: collapse control lives inside the tab strip with an accessible name', () => {
  const barStart = bottomPanel.indexOf('<div className="wb-panel-bar">');
  assert.ok(barStart !== -1, 'panel bar markup must exist');
  const sectionEnd = bottomPanel.indexOf('</section>', barStart);
  const barBlock = bottomPanel.slice(barStart, sectionEnd);
  assert.match(barBlock, /label=\{t\('shell\.panelHide'\)\}/, 'collapse button must carry the panelHide accessible name');
  assert.match(barBlock, /onClick=\{\(\) => onToggle\(false\)\}/, 'collapse button must sit inside the strip block');
  for (const [name, dict] of [['ko', ko], ['en', en]]) {
    assert.match(dict, /'shell\.panelHide':/, `shell.panelHide key must exist in ${name} dict`);
  }
});

test('M12: tall drag range is preserved (min, max, keyboard, double-click reset)', () => {
  const usage = bottomPanel.match(/minHeight=\{(\d+)\}[\s\S]*?maxHeight=\{(\d+)\}/);
  assert.ok(usage, 'BottomPanel must bound HeightResizer with min/max');
  assert.ok(Number(usage[1]) <= 120, `min must allow compact/shut-adjacent drag, got ${usage[1]}`);
  assert.ok(Number(usage[2]) >= 480, `max must preserve tall drag, got ${usage[2]}`);
  for (const key of ['ArrowUp', 'ArrowDown', 'Home', 'End']) {
    assert.ok(heightResizer.includes(`'${key}'`), `HeightResizer must handle ${key}`);
  }
  assert.match(heightResizer, /onDoubleClick=\{\(\) => updateHeight\(defaultHeight\)\}/, 'double-click must reset to the default');
});

test('M12 RED: compact default applies before first paint (no content-sized flash)', () => {
  // HEAD gap behind the live 449px measurement: the section gets its height
  // only from HeightResizer's useEffect (post-paint) and workbench.css sets
  // no height on .wb-panel, so first paint sizes to content (449px with
  // Problems findings). Any one of these closes it: a style height on the
  // section, a CSS height on .wb-panel, or useLayoutEffect in HeightResizer.
  const sectionHasStyleHeight = /<section[^>]*style=\{[^}]*height/.test(bottomPanel);
  const cssHasPanelHeight = /(^|\n)\.wb-panel\s*\{[^}]*?(?<![\w-])height\s*:/.test(workbenchCss);
  const layoutEffect = heightResizer.includes('useLayoutEffect');
  assert.ok(
    sectionHasStyleHeight || cssHasPanelHeight || layoutEffect,
    'M12 HEAD gap (live measured 449px open tabpanel): no declarative pre-paint panel height — '
    + 'section style height, .wb-panel CSS height, or useLayoutEffect all absent',
  );
});
