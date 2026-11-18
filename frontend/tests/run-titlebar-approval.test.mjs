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

/* Todo 10: the title-bar Run is the approval path, never a start button. */

test('title-bar Preview run and Run open the run preview on the active case', async () => {
  const commands = await read('../src/shell/useWorkbenchCommands.ts');
  assert.match(commands, /else if \(id === 'preview-run' \|\| id === 'open-run'\) selectView\('run'\)/, 'both commands route to Run');
  assert.match(commands, /requestRunPreview/, 'both commands request a preview on the active case');
});

test('title-bar Run cannot approve or start anything by itself', async () => {
  const [title, commands] = await Promise.all([
    read('../src/shell/TitleBar.tsx'),
    read('../src/shell/useWorkbenchCommands.ts'),
  ]);
  assert.doesNotMatch(title, /executeApproval|runExecute|sweepExecute/, 'no execution primitive in the title bar');
  assert.doesNotMatch(commands, /executeApproval|runExecute|sweepExecute/, 'commands never execute, they only navigate and request');
  assert.match(title, /onClick=\{onPreviewRun\}/, 'Preview run stays wired');
  assert.match(title, /onClick=\{onOpenRun\}/, 'Run stays wired');
});

test('RunView consumes a pending preview request through the existing preview path', async () => {
  const [view, request] = await Promise.all([
    read('../src/RunView.tsx'),
    read('../src/runPreviewRequest.ts'),
  ]);
  assert.match(request, /requestRunPreview/, 'a session-only flag carries the request');
  assert.match(view, /previewRequested|consumePreviewRequest/, 'RunView observes the flag');
  assert.match(view, /doPreview/, 'consuming the flag calls the existing preview, never a start');
  assert.doesNotMatch(view, /consumePreviewRequest[\s\S]*?doRun|doRun[\s\S]*?consumePreviewRequest/, 'consuming never reaches execution');
});
