import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* Todo 15 probe follow-up: at 320/390 the title row crushed the case chip
 * to 26px and pushed body.scrollWidth to 562 (RS-006 + CF-701 HIGH). The
 * narrow title bar must scroll inside itself instead of crushing or
 * overflowing the page, and the case chip must keep a usable width. */

test('the narrow title bar scrolls inside itself instead of widening the page', async () => {
  const css = await read('../src/styles/workbench.css');
  assert.match(css, /@media\s*\(max-width:\s*768px\)[\s\S]*?\.wb-titlebar[^{]*\{[^}]*overflow-x:\s*auto/s, 'the title bar scrolls horizontally when narrow');
});

test('the case chip keeps a usable width in the narrow title bar', async () => {
  const css = await read('../src/styles/workbench.css');
  assert.match(css, /@media\s*\(max-width:\s*768px\)[\s\S]*?\.wb-crumb\s+\.case-chip[^{]*\{[^}]*min-width:\s*(4\d|5\d|[1-9]\d\d+)px/s, 'the chip never crushes below a usable width');
});
