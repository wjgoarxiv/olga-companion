import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('Given the workbench shell, when regions mount, then focus order runs title bar > activity > explorer > centre > dock > panel', async () => {
  // Given the application shell source.
  const app = await read('../src/App.tsx');

  // When region order is inspected.
  const order = ['<TitleBar', '<ActivityBar', '<ExplorerPanel', '<main', '<ChatDockView', '<BottomPanel', '<StatusBar'];
  const positions = order.map((marker) => app.indexOf(marker));

  // Then every region mounts in focus order.
  for (const [index, marker] of order.entries()) {
    assert.ok(positions[index] >= 0, `${marker} mounts in the shell`);
    if (index > 0) assert.ok(positions[index] > positions[index - 1], `${marker} follows ${order[index - 1]} in DOM order`);
  }
});
