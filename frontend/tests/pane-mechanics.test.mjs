import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

// W2-L2 (M2 mechanics + M3 placement) RED-first suite. Each test fails on
// HEAD and passes after the wave item lands. Pure/source-level except where
// noted; no approval/chat/send/save actuation anywhere in this file.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = (p) => fs.readFileSync(path.join(root, 'src', p), 'utf8');

const mapStore = (entries = {}) => {
  const m = new Map(Object.entries(entries));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    snapshot: () => Object.fromEntries(m),
  };
};

test('M2: single pane spec object pins defaults, clamps and storage keys', async () => {
  const { PANE_SPEC } = await import('../src/shell/paneSpec.ts');
  assert.deepEqual(PANE_SPEC.dock, {
    defaultWidth: 384, minWidth: 300, maxWidth: 560,
    storageKey: 'olga-companion.dock.width',
  });
  assert.deepEqual(PANE_SPEC.explorer, {
    defaultWidth: 248, minWidth: 200, maxWidth: 480,
    storageKey: 'olga-companion.explorer.width',
  });
  assert.deepEqual(PANE_SPEC.panel, {
    defaultHeight: 168, minHeight: 120, maxHeight: 480,
    storageKey: 'olga-companion.panel.height',
  });
  assert.equal(PANE_SPEC.centreFloor, 320);
});

test('M2: re-clamp debits overflow from the dock first, floors at min', async () => {
  const { reclampPersistedWidths } = await import('../src/shell/paneSpec.ts');
  const store = mapStore({
    'olga-companion.dock.width': '560',
    'olga-companion.explorer.width': '480',
  });
  const out = reclampPersistedWidths(1280, store);
  assert.equal(out.dock, 480);
  assert.equal(out.explorer, 480);
  assert.equal(store.snapshot()['olga-companion.dock.width'], '480');
});

test('M2: re-clamp spills to the explorer when the dock hits min, never below', async () => {
  const { reclampPersistedWidths } = await import('../src/shell/paneSpec.ts');
  const store = mapStore({
    'olga-companion.dock.width': '560',
    'olga-companion.explorer.width': '480',
  });
  const out = reclampPersistedWidths(1000, store);
  assert.equal(out.dock, 300);
  assert.equal(out.explorer, 380);
  assert.ok(out.dock >= 300 && out.explorer >= 200);
});

test('M2: re-clamp never touches open/closed state or foreign keys', async () => {
  const { reclampPersistedWidths } = await import('../src/shell/paneSpec.ts');
  const store = mapStore({
    'olga-companion.dock.width': '560',
    'olga-companion.explorer.width': '480',
    'olga-companion.dock.open': 'false',
    'unrelated.key': 'keep',
  });
  reclampPersistedWidths(1280, store);
  const snap = store.snapshot();
  assert.equal(snap['olga-companion.dock.open'], 'false');
  assert.equal(snap['unrelated.key'], 'keep');
});

test('M2: re-clamp yields to the approval pin (no centre-floor debit)', async () => {
  const { reclampPersistedWidths } = await import('../src/shell/paneSpec.ts');
  const store = mapStore({
    'olga-companion.dock.width': '560',
    'olga-companion.explorer.width': '480',
  });
  const out = reclampPersistedWidths(1000, store, { approvalOpen: true });
  assert.equal(out.dock, 560);
  assert.equal(out.explorer, 480);
});

test('M2: valuetext is localized through resize.pixels, never hardcoded', async () => {
  const handle = src('PanelResizeHandle.tsx');
  const height = src('shell/HeightResizer.tsx');
  assert.ok(!handle.includes('pixels`') && !handle.includes("' pixels'"), 'dock valuetext must not hardcode English');
  assert.ok(!height.includes('pixels`') && !height.includes("' pixels'"), 'panel valuetext must not hardcode English');
  assert.match(handle, /resize\.pixels/);
  assert.match(height, /resize\.pixels/);
  const { translate } = await import('../src/i18n/index.ts');
  assert.equal(translate('ko', 'resize.pixels', { width: 384 }), '384픽셀');
  assert.equal(translate('en', 'resize.pixels', { width: 384 }), '384 px');
});

test('M2: separators expose aria-keyshortcuts; dialog documents resize keys', async () => {
  assert.match(src('PanelResizeHandle.tsx'), /aria-keyshortcuts="ArrowLeft ArrowRight Home End"/);
  assert.match(src('shell/HeightResizer.tsx'), /aria-keyshortcuts="ArrowUp ArrowDown Home End"/);
  const dialog = src('shell/ShortcutsDialog.tsx');
  assert.match(dialog, /resize\.shortcutsTitle/);
  assert.match(dialog, /resize\.scNudge/);
  const { translate } = await import('../src/i18n/index.ts');
  for (const key of ['resize.shortcutsTitle', 'resize.scNudge', 'resize.scLarge', 'resize.scEnds']) {
    assert.ok(translate('ko', key).length > 0, `${key} ko`);
    assert.ok(translate('en', key).length > 0, `${key} en`);
    assert.ok(!/[\u3131-\u318e\uac00-\ud7a3]/.test(translate('en', key)), `${key} en carries no Hangul`);
  }
});

test('M2: coachmark predicate — dismiss persists, approval suppresses, fresh shows', async () => {
  const { shouldShowResizeCoachmark } = await import('../src/shell/resizeCoachmarkState.ts');
  assert.equal(shouldShowResizeCoachmark({ dismissed: true, hasStoredWidth: false, approvalActive: false }), false);
  assert.equal(shouldShowResizeCoachmark({ dismissed: false, hasStoredWidth: true, approvalActive: false }), false);
  assert.equal(shouldShowResizeCoachmark({ dismissed: false, hasStoredWidth: false, approvalActive: true }), false);
  assert.equal(shouldShowResizeCoachmark({ dismissed: false, hasStoredWidth: false, approvalActive: false }), true);
});

test('M2: explicit user actions mark the pane touched (mounts never do)', async () => {
  const { hasUserResize, markUserResize, userResizeKey } = await import('../src/shell/paneSpec.ts');
  const store = mapStore({});
  assert.equal(hasUserResize('olga-companion.dock.width', store), false);
  markUserResize('olga-companion.dock.width', store);
  assert.equal(hasUserResize('olga-companion.dock.width', store), true);
  assert.equal(store.snapshot()['olga-companion.dock.width.touched'], '1');
  assert.equal(userResizeKey('olga-companion.dock.width'), 'olga-companion.dock.width.touched');
  assert.match(src('PanelResizeHandle.tsx'), /markUserResize\(storageKey\)/);
  assert.match(src('shell/HeightResizer.tsx'), /markUserResize\(storageKey\)/);
});

test('M2: coachmark never moves focus and reuses existing copy keys', () => {
  const coach = src('shell/ResizeCoachmark.tsx');
  assert.ok(!coach.includes('autoFocus') && !coach.includes('.focus()'), 'coachmark must never steal focus');
  assert.match(coach, /resize\.hint/);
  assert.match(coach, /shell\.close/);
  assert.match(coach, /data-testid="resize-coachmark"/);
  assert.ok(!/resize\.coachmark\w*Text|resize\.coachmark\w*Label/.test(coach), 'no new copy keys for coachmark wording');
});

test('M3: recent pill lives in the timeline, not the composer footer', () => {
  const view = src('ChatView.tsx');
  const footerStart = view.indexOf('<div className="composer-actions">');
  assert.ok(footerStart !== -1, 'composer footer must exist');
  const timelineStart = view.indexOf('data-testid="chat-timeline"');
  const pillAt = view.indexOf('onScrollToBottom}');
  assert.ok(timelineStart !== -1 && pillAt > timelineStart, 'pill must render inside the timeline region');
  const footerBlock = view.slice(footerStart, view.indexOf('</div>', view.indexOf('composer.send')));
  assert.ok(!footerBlock.includes('recentChat'), 'footer must not contain the recent pill');
  assert.match(view, /position:\s*['"]?sticky['"]?/, 'pill anchors with sticky positioning');
});

test('M3: recent pill is opaque so it never shows card text through it', () => {
  const view = src('ChatView.tsx');
  const pillAt = view.indexOf('onClick={props.onScrollToBottom}');
  const open = view.lastIndexOf('<Button', pillAt);
  assert.ok(open !== -1, 'pill must be a Button');
  assert.ok(!/variant="quiet"/.test(view.slice(open, pillAt)), 'a transparent quiet pill overlaps the timeline text');
});

test('M3: idle footer keeps exactly clear + send; pill keeps action contract', () => {
  const view = src('ChatView.tsx');
  assert.match(view, /aria-label=\{t\('chat\.recentChatAria'\)\}/);
  assert.match(view, /onClick=\{props\.onScrollToBottom\}/);
  assert.ok(!view.includes('autoFocus'), 'pill must not steal focus on mount');
  assert.ok(view.includes('aria-hidden="true">↓<') || view.includes("aria-hidden=\"true\">↓<"), 'pill carries a visible down glyph');
});
