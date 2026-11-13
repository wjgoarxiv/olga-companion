import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('xai action keeps one accessible name and reaches 44px', async () => {
  const [button, css] = await Promise.all([
    read('../src/ui/Button.tsx'),
    read('../src/styles/settings.css'),
  ]);
  assert.match(button, /\{busy && busyLabel &&/, 'the width-reserve span renders only while busy');
  assert.match(button, /aria-live/, 'busy copy is announced without entering the idle name');
  assert.match(
    css,
    /\.xai-connect\s+\.ui-button\s*\{[^}]*min-height:\s*44px/s,
    'the xai action matches the other provider buttons at desktop widths',
  );
});

test('the conversation keeps exactly one bounded scroll container at short heights', async () => {
  const css = await read('../src/styles/chat-messages.css');
  assert.match(
    css,
    /\.timeline\s*\{[^}]*min-height:\s*0/s,
    'the timeline grid row shrinks instead of spilling under the composer',
  );
});

test('results intro copy speaks Korean to beginners', async () => {
  const [prompts, layout, profile, ko, en] = await Promise.all([
    read('../src/ResultsPrompts.tsx'),
    read('../src/ResultsLayout.tsx'),
    read('../src/ProfilePanel.tsx'),
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
  ]);
  assert.match(prompts, /title=\{t\('results\.pickTitle'\)\}/);
  assert.match(ko, /TPL/, 'technical tokens stay verbatim');
  assert.match(en, /TPL/, 'technical tokens stay verbatim');
  assert.doesNotMatch(prompts, /Choose an output to review/);
  assert.doesNotMatch(layout, /Pick a variable to plot its trend\./);
  assert.match(layout, /t\('results\.pickVarHint'\)/);
  assert.doesNotMatch(profile, /Pick a variable to plot its spatial profile/);
});
