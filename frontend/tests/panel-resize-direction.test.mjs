import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const sourceUrl = new URL('../src/PanelResizeHandle.tsx', import.meta.url);

test('resize handle reverses pointer and keyboard width changes when the panel grows left', async () => {
  // Given: the shared resize handle source.
  const source = await readFile(sourceUrl, 'utf8');

  // When: its direction contract and movement calculations are inspected.
  // Then: grow-left reverses both pointer drag and arrow-key width deltas.
  assert.match(source, /direction\?:\s*'grow-right'\s*\|\s*'grow-left'/);
  assert.match(source, /direction\s*=\s*'grow-right'/);
  assert.match(source, /'grow-right':\s*1/);
  assert.match(source, /'grow-left':\s*-1/);
  assert.match(source, /directionSign\s*=\s*DIRECTION_SIGN\[direction\]/);
  assert.match(source, /event\.clientX\s*-\s*drag\.startX\)\s*\*\s*directionSign/);
  assert.match(source, /width\s*-\s*step\s*\*\s*directionSign/);
  assert.match(source, /width\s*\+\s*step\s*\*\s*directionSign/);
});
