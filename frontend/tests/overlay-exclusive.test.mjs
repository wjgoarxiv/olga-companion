import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* BL-01 (v0.1.4): at 769-1023 px both drawers are overlays, so two open at
 * once stack on top of the centre. Only one may be open in the band, and the
 * stored (inline) pane width must never beat the band's own clamp. */

test('the band predicate matches the 769-1023 breakpoints exactly', async () => {
  const { isOverlayBandWidth, OVERLAY_BAND_QUERY } = await import('../src/shell/overlayExclusive.mjs');
  assert.equal(isOverlayBandWidth(768), false);
  assert.equal(isOverlayBandWidth(769), true);
  assert.equal(isOverlayBandWidth(960), true);
  assert.equal(isOverlayBandWidth(1023), true);
  assert.equal(isOverlayBandWidth(1024), false);
  assert.equal(OVERLAY_BAND_QUERY, '(min-width: 769px) and (max-width: 1023px)');
});

test('outside the band the two panes stay independent', async () => {
  const { resolveOverlayExclusive } = await import('../src/shell/overlayExclusive.mjs');
  const both = { dockOpen: true, explorerOpen: true };
  assert.deepEqual(resolveOverlayExclusive(both, 'dock', false), both);
  assert.deepEqual(resolveOverlayExclusive(both, 'explorer', false), both);
  assert.deepEqual(resolveOverlayExclusive(both, null, false), both);
});

test('in the band, opening one drawer closes the other', async () => {
  const { resolveOverlayExclusive } = await import('../src/shell/overlayExclusive.mjs');
  assert.deepEqual(
    resolveOverlayExclusive({ dockOpen: true, explorerOpen: true }, 'dock', true),
    { dockOpen: true, explorerOpen: false },
    'opening the dock closes the explorer',
  );
  assert.deepEqual(
    resolveOverlayExclusive({ dockOpen: true, explorerOpen: true }, 'explorer', true),
    { dockOpen: false, explorerOpen: true },
    'opening the explorer closes the dock',
  );
});

test('in the band, closing a drawer never opens or closes the other', async () => {
  const { resolveOverlayExclusive } = await import('../src/shell/overlayExclusive.mjs');
  assert.deepEqual(
    resolveOverlayExclusive({ dockOpen: false, explorerOpen: true }, 'dock', true),
    { dockOpen: false, explorerOpen: true },
  );
  assert.deepEqual(
    resolveOverlayExclusive({ dockOpen: false, explorerOpen: false }, 'explorer', true),
    { dockOpen: false, explorerOpen: false },
  );
});

test('entering the band with both open keeps the dock (it carries the approval card)', async () => {
  const { resolveOverlayExclusive } = await import('../src/shell/overlayExclusive.mjs');
  assert.deepEqual(
    resolveOverlayExclusive({ dockOpen: true, explorerOpen: true }, null, true),
    { dockOpen: true, explorerOpen: false },
  );
  assert.deepEqual(
    resolveOverlayExclusive({ dockOpen: false, explorerOpen: true }, null, true),
    { dockOpen: false, explorerOpen: true },
    'a single open drawer is left alone',
  );
});

test('a first load inside the band opens one drawer, a first load docked opens both', async () => {
  const { exclusiveFor, loadWorkbenchLayout } = await import('../src/shell/useWorkbenchLayout.ts');
  const stored = loadWorkbenchLayout();
  assert.equal(stored.dockOpen && stored.explorerOpen, true, 'a fresh profile defaults to both open');
  const band = exclusiveFor(stored, null, true);
  assert.equal(Number(band.dockOpen) + Number(band.explorerOpen), 1, 'exactly one drawer open in the band');
  const docked = exclusiveFor(stored, null, false);
  assert.equal(docked.dockOpen && docked.explorerOpen, true, 'docked widths keep both open');
});

test('the layout store routes both toggles through the exclusive rule and watches the band', async () => {
  const store = await read('../src/shell/useWorkbenchLayout.ts');
  assert.match(store, /overlayExclusive/, 'the pure rule is imported');
  assert.match(store, /resolveOverlayExclusive\(/, 'the rule is applied');
  assert.match(store, /exclusiveFor\(\{[^\n]*changed, inBand\)/, 'a drawer choice applies the rule to the effective flags');
  assert.match(store, /setDockOpen = useCallback\([^\n]*choose\('dock'/, 'setDockOpen uses the rule');
  assert.match(store, /setExplorerOpen = useCallback\([^\n]*choose\('explorer'/, 'setExplorerOpen uses the rule');
  assert.match(store, /OVERLAY_BAND_QUERY[\s\S]{0,500}addEventListener\('change'/, 'entering the band re-resolves live');
});

test('the band clamps the drawer width even when an inline stored width exists', async () => {
  const css = await read('../src/styles/workbench.css');
  const band = css.match(/@media\s*\(min-width:\s*769px\)\s*and\s*\(max-width:\s*1023px\)\s*\{([\s\S]*?)\n\}/);
  assert.ok(band, 'the overlay band exists and keeps its 769/1023 breakpoints');
  assert.match(band[1], /\.wb-explorer\s*\{[^}]*width:\s*min\(320px,\s*72vw\)[^}]*max-width:\s*min\(320px,\s*72vw\)/s, 'the explorer width is capped at the band clamp');
  assert.match(band[1], /\.wb-dock\s*\{[^}]*width:\s*min\(384px,\s*80vw\)[^}]*max-width:\s*min\(384px,\s*80vw\)/s, 'the dock width is capped at the band clamp');
});

test('the resize handle re-clamps stored widths when the viewport crosses 1024', async () => {
  const handle = await read('../src/PanelResizeHandle.tsx');
  assert.match(handle, /addEventListener\('resize'/, 'listens to viewport resizes');
  assert.match(handle, /isOverlayBandWidth/, 'tracks the crossing with the shared band predicate');
  const body = handle.slice(handle.indexOf("addEventListener('resize'") - 600, handle.indexOf("addEventListener('resize'") + 600);
  assert.match(body, /reclampPersistedWidths/, 'the re-clamp runs on that crossing');
});
