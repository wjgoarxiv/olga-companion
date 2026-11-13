import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* W2-L3a (M6): title-bar actions gate on the active case. Presence only
   (R FIX-FIRST): disabled + aria-describedby reason. Paint (Wave 3) keeps
   the dashed-disabled Button pattern and is asserted elsewhere. */

test('title-bar Validate / Preview run / Run disable without a case', async () => {
  const title = await read('../src/shell/TitleBar.tsx');
  for (const handler of ['onValidate', 'onPreviewRun', 'onOpenRun']) {
    assert.match(title, new RegExp(`onClick=\\{${handler}\\}[\\s\\S]{0,200}?disabled=`), `${handler} button carries a disabled prop`);
  }
  assert.match(title, /aria-describedby=.*titlebar-needcase-hint/, 'gated buttons describe the reason node');
  assert.match(title, /id="titlebar-needcase-hint"[\s\S]*?titlebar\.needCase/, 'reason node renders t(titlebar.needCase)');
});

test('gating values come from the commands derivation, bodies unchanged', async () => {
  const [title, commands] = await Promise.all([
    read('../src/shell/TitleBar.tsx'),
    read('../src/shell/useWorkbenchCommands.ts'),
  ]);
  assert.match(title, /from '\.\/useWorkbenchCommands'/, 'TitleBar takes the derivation from useWorkbenchCommands');
  assert.match(commands, /activeCaseName/, 'hook accepts the read-only activeCaseName');
  assert.match(commands, /canValidate/, 'hook derives canValidate');
  assert.match(commands, /canPreview/, 'hook derives canPreview');
  assert.match(commands, /canRun/, 'hook derives canRun');
  assert.match(commands, /activeCaseName != null/, 'derivation is activeCaseName != null');
  assert.doesNotMatch(commands, /executeApproval|runExecute|sweepExecute/, 'command bodies still never execute');
});

test('titlebar.needCase exists in ko and en with the specified copy', async () => {
  const [ko, en] = await Promise.all([read('../src/i18n/ko.ts'), read('../src/i18n/en.ts')]);
  assert.match(ko, /'titlebar\.needCase': '먼저 사례를 고르세요'/, 'ko copy');
  assert.match(en, /'titlebar\.needCase': 'Select a case first'/, 'en copy');
});
