import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const readCss = async () => {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((match) => read(`../src/${match[1]}`)));
  return [root, ...imported].join('\n');
};

/* Todo 10: the bottom-panel Run console streams the run log and progress. */

test('run lifecycle publishes entries and progress to a shared console store', async () => {
  const [store, actions, lifecycle] = await Promise.all([
    read('../src/runConsole.ts'),
    read('../src/useRunActions.ts'),
    read('../src/useRunLifecycle.ts'),
  ]);
  assert.match(store, /subscribeRunConsole|getRunConsoleSnapshot/, 'one shared store bridges RunView and the panel');
  assert.match(store, /logTail|entries/, 'entries plus the latest solver log tail');
  assert.match(actions, /pushRunConsoleEntry|setRunConsoleSnapshot/, 'preview/start/cancel publish lifecycle entries');
  assert.match(lifecycle, /setRunConsoleSnapshot|pushRunConsoleEntry/, 'poll ticks refresh progress and log tail');
});

test('the bottom-panel console tab renders the run feed, not the empty note', async () => {
  const [panel, consolePanel] = await Promise.all([
    read('../src/shell/BottomPanel.tsx'),
    read('../src/RunConsolePanel.tsx'),
  ]);
  assert.match(panel, /RunConsolePanel/, 'the console tab hosts the feed');
  assert.doesNotMatch(panel, /shell\.consoleEmpty/, 'the static empty note is gone');
  assert.match(consolePanel, /run\.logLabel|consoleLogLabel/, 'the solver log keeps an accessible name');
  assert.match(consolePanel, /tabular-nums/, 'sim time ticks without jitter');
});
