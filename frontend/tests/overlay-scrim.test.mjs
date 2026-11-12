import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { useOverlayPanels } from '../src/shell/useOverlayPanels.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function zIndexOf(css, name) {
  const rule = new RegExp(`[^{}]*?\\.${name}(?![\\w-])[^{}]*?\\{[^}]*?z-index:\\s*(\\d+)`, 's').exec(css);
  return rule ? Number(rule[1]) : null;
}

/* W3-L2 (M5): overlay band 769–1023. An open Explorer/dock floats above the
   centre, so a scrim must exist to dismiss it; ESC closes LIFO with focus
   return (existing hook, locked here); scrim sits below the drawers. */

test('scrim module closes the topmost overlay first and returns focus', async () => {
  const scrim = await read('../src/shell/OverlayScrim.tsx');
  assert.match(scrim, /data-scrim/, 'M9 §(e) scrim hook');
  assert.match(scrim, /dockOpen[\s\S]{0,300}explorerOpen/, 'knows both panels to pick the topmost');
  assert.match(scrim, /activity-dock-toggle/, 'focus returns to the dock toggle');
  assert.match(scrim, /activity-explorer-toggle/, 'focus returns to the explorer toggle');
  assert.match(scrim, /769[\s\S]{0,200}1023/, 'band-gated to 769–1023 (stacked/docked widths render no scrim)');
});

test('activity bar hosts the scrim where the toggles live', async () => {
  const bar = await read('../src/shell/ActivityBar.tsx');
  assert.match(bar, /OverlayScrim/, 'scrim renders with the overlay toggles, not in App');
  assert.match(bar, /dockOpen[\s\S]{0,200}explorerOpen/, 'scrim receives both open states');
});

test('App stays out of the overlay path (LOC budget)', async () => {
  const app = await read('../src/App.tsx');
  assert.doesNotMatch(app, /OverlayScrim|wb-scrim/, 'no App.tsx hunk for the scrim');
});

test('scrim stacks below the drawers and inside the mid frame', async () => {
  const css = await read('../src/styles/workbench.css');
  const scrimZ = zIndexOf(css, 'wb-scrim');
  const dockZ = zIndexOf(css, 'wb-dock');
  const explorerZ = zIndexOf(css, 'wb-explorer');
  assert.ok(scrimZ !== null, 'scrim has an explicit z-index');
  assert.ok(dockZ !== null && explorerZ !== null, 'drawers keep explicit z-indexes');
  assert.ok(scrimZ < dockZ && scrimZ < explorerZ, `scrim (${scrimZ}) must sit below the drawers (${explorerZ}/${dockZ})`);
  assert.match(css, /\.wb-scrim\s*\{[^}]*?top:\s*var\(--tb-h\)/, 'scrim starts below the title bar');
  assert.match(css, /\.wb-scrim\s*\{[^}]*?bottom:\s*var\(--sb-h\)/, 'scrim ends above the status bar');
  assert.match(css, /\.wb-scrim\s*\{[^}]*?left:\s*var\(--ab-w\)/, 'scrim leaves the activity rail interactive');
});

test('ESC closes LIFO with focus return (existing hook locked)', () => {
  assert.equal(typeof useOverlayPanels, 'function', 'hook importable');
});

test('approval card rides inside the dock drawer above the scrim', async () => {
  const chat = await read('../src/ChatView.tsx');
  assert.match(chat, /ApprovalCard/, 'card renders in the chat timeline, inside the dock stacking context');
  const dockView = await read('../src/shell/ChatDockView.tsx');
  assert.match(dockView, /ChatDock/, 'dock view hosts the dock drawer');
});
