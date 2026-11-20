import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

// Owner spacing fix-up: each rule below failed before the fix and passes after.

test('explorer rows are a no-overflow grid with a fixed suffix/size that never clips', async () => {
  const css = await read('../src/styles/workbench.css');
  assert.match(
    css,
    /\.wb-explorer-item\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:[^}]*minmax\(0,\s*1fr\)[^}]*auto[^}]*auto/s,
    'row is icon | name | suffix | size with the name the only flexible track',
  );
  assert.match(
    css,
    /\.wb-explorer-ext[^{]*\{[^}]*flex:\s*0\s*0\s*auto/s,
    'the suffix is fixed and never clipped',
  );
  assert.match(
    css,
    /\.wb-explorer-meta\s*\{[^}]*white-space:\s*nowrap/s,
    'the size stays on one line',
  );
  assert.match(
    css,
    /\.wb-explorer-tree\s*\{[^}]*overflow-x:\s*(hidden|clip)/s,
    'the tree never scrolls sideways',
  );
  assert.match(
    css,
    /\.wb-explorer-name-head\s*\{[^}]*text-overflow:\s*ellipsis[^}]*white-space:\s*nowrap/s,
    'the head truncates with an ellipsis only when it really overflows',
  );
});

test('explorer rows stay compact and size from the density target token', async () => {
  const [css, base] = await Promise.all([
    read('../src/styles/workbench.css'),
    read('../src/styles/base.css'),
  ]);
  assert.match(
    css,
    /\.wb-explorer-item\s*\{[^}]*min-height:\s*var\(--tgt\)/s,
    'the row sizes from the density target token (border-box total)',
  );
  assert.match(
    css,
    /\.wb-explorer-item\s*\{[^}]*padding:\s*6px var\(--sp-2\)/s,
    'tight padding leaves a compact ~32px visual band inside the target',
  );
  assert.match(base, /\[data-density="comfortable"\][\s\S]*?--tgt:\s*calc\(44px/, 'the comfortable hit target stays 44px');
});

test('explorer shows full names and never mid-truncates', async () => {
  const panel = await read('../src/shell/ExplorerPanel.tsx');
  assert.doesNotMatch(panel, /displayStem/, 'no mid-truncation in the tree');
  assert.match(panel, /title=\{item\.name\}/, 'the full name stays on the tooltip');
  assert.match(panel, /aria-label=\{`?\$\{item\.name\}/, 'the full name stays on the accessible name');
});

test('the dock header, timeline and composer share one token gutter', async () => {
  const [wb, chat] = await Promise.all([
    read('../src/styles/workbench.css'),
    read('../src/styles/chat-messages.css'),
  ]);
  assert.match(
    wb,
    /\.chat-head\s*\{[^}]*padding:[^;}]*var\(--sp-/s,
    'the Conversation header carries the dock gutter',
  );
  assert.match(
    chat,
    /\.timeline\s*\{[^}]*padding:[^;}]*var\(--sp-/s,
    'the timeline inset reads the same token gutter',
  );
  assert.match(
    wb,
    /\.chat\s*\{[^}]*min-width:\s*0/s,
    'the dock chat can shrink inside the resizable dock',
  );
  assert.match(
    wb,
    /\.chat-head-actions\s*\{[^}]*flex-wrap:\s*wrap/s,
    'the header actions wrap instead of clipping Chats',
  );
});

test('the bottom-panel strip spans the full width with the collapse button inside it', async () => {
  const [wb, panel] = await Promise.all([
    read('../src/styles/workbench.css'),
    read('../src/shell/BottomPanel.tsx'),
  ]);
  assert.match(
    wb,
    /\.wb-panel-bar\s*\{[^}]*display:\s*grid/s,
    'the strip is a full-width grid',
  );
  assert.match(
    wb,
    /\.wb-panel-bar[^{]*\.ui-tabpanel\s*\{[^}]*grid-column:\s*1\s*\/\s*-1/s,
    'the active panel drops below the strip, full width',
  );
  assert.match(
    panel,
    /defaultHeight=\{16\d\}|defaultHeight=\{17\d\}|defaultHeight=\{18\d\}/,
    'the panel defaults to a compact one-line height (160-180px)',
  );
});

test('the workspace centre no longer duplicates the explorer list', async () => {
  const [view, centre] = await Promise.all([
    read('../src/WorkspaceView.tsx'),
    read('../src/shell/CentreViews.tsx'),
  ]);
  assert.doesNotMatch(view, /ws-files/, 'the duplicate centre list is gone');
  assert.doesNotMatch(view, /workspace-case-sidebar/, 'the centre sidebar anchor is gone');
  assert.match(view, /TopologyMap/, 'the freed width keeps the topology canvas');
  assert.match(view, /OPEN_TAB_PREVIEW_EVENT/, 'tab previews still resolve through the canvas');
  assert.match(centre, /<WorkspaceView/, 'the centre still mounts the case surface');
});
