import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import test from 'node:test';

// T2: the jagged pixel set is gone. Every symbol is a smooth vector icon:
// no crispEdges anywhere in frontend/src, no PixelIcon/Icon3D component or
// raster-icon reference left, and all 34 legacy names still resolve in Icon.
const SRC = new URL('../src/', import.meta.url);

async function walk(dir, out = []) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const url = new URL(entry.name, dir.href.endsWith('/') ? dir : new URL(dir.href + '/'));
    if (entry.isDirectory()) await walk(new URL(url.href + '/'), out);
    else if (/\.(tsx?|mjs|css)$/.test(entry.name)) out.push(url);
  }
  return out;
}

const NAMES = ['case', 'edit', 'validate', 'run', 'results', 'chat', 'settings',
  'fluid', 'warning', 'ok', 'folder', 'file', 'graph', 'export',
  'collapse', 'grip', 'chevron', 'close', 'send', 'node', 'search',
  'sun', 'moon', 'mark', 'pipe', 'source', 'sink', 'valve', 'riser', 'separator',
  'plus', 'minus', 'bar', 'cross'];

test('no crispEdges anywhere in frontend/src: icons and mark are smooth vectors', async () => {
  const files = await walk(SRC);
  assert.ok(files.length > 50, `scanned the source tree (got ${files.length} files)`);
  const hits = [];
  for (const file of files) {
    const body = await readFile(file, 'utf8');
    if (/crispEdges/.test(body)) hits.push(file.href);
  }
  assert.deepEqual(hits, [], `smooth vectors only, no crispEdges: ${hits.join(', ')}`);
});

test('no PixelIcon / Icon3D component or raster icon reference remains in frontend/src', async () => {
  const files = await walk(SRC);
  const hits = [];
  for (const file of files) {
    const body = await readFile(file, 'utf8');
    if (/PixelIcon|Icon3D|ui-icon3d|\/icons\//.test(body)) hits.push(file.href);
  }
  assert.deepEqual(hits, [], `vector Icon only: ${hits.join(', ')}`);
});

test('Icon.tsx maps all 34 legacy names, decorative by default, smooth strokes', async () => {
  const src = await readFile(new URL('../src/ui/Icon.tsx', import.meta.url), 'utf8');
  assert.match(src, /export type IconName/, 'the IconName union is exported');
  for (const name of NAMES) {
    assert.match(src, new RegExp(`'${name}'`), `${name} still resolves`);
  }
  assert.match(src, /export function Icon\(/, 'Icon is exported');
  assert.match(src, /export function IconInSvg\(/, 'IconInSvg is exported');
  assert.match(src, /aria-hidden/, 'decorative by default');
  assert.match(src, /role="img"|role:\s*'img'|role=\{'img'\}/, 'label makes it role=img');
  assert.match(src, /strokeLinecap="round"|stroke-linecap="round"/, 'round caps, never stepped');
  assert.match(src, /currentColor/, 'icons paint in currentColor');
  assert.match(src, /lucide-react/, 'generic symbols reuse lucide-react');
  assert.doesNotMatch(src, /crispEdges/, 'no stepped rendering in the icon set');
});

test('Icon renders at its size prop: the --px var feeds the .ui-icon rule', async () => {
  const src = await readFile(new URL('../src/ui/Icon.tsx', import.meta.url), 'utf8');
  assert.match(src, /'--px'/, 'Icon sets --px so .ui-icon widths match size, not the 24 fallback');
});
