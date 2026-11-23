// About screen (security review A5): who made the app, its licence, and that it is not an SLB product.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');
const HANGUL = /[ㄱ-ㆎ가-힣]/;
const KEYS = ['about.title', 'about.version', 'about.author', 'about.license', 'about.notice', 'about.slb', 'about.open', 'shell.cmdAbout'];

test('the palette lists About and running it opens the About dialog', () => {
  assert.match(src('shell/keymap.ts'), /\| 'show-about'/);
  assert.match(src('shell/commands.ts'), /\{ id: 'show-about', labelKey: 'shell\.cmdAbout' \}/);
  assert.match(src('shell/useWorkbenchCommands.ts'), /id === 'show-about'\) requestAboutOpen\(\)/);
});

test('the activity bar footer has an About button and hosts the dialog', () => {
  const bar = src('shell/ActivityBar.tsx');
  assert.match(bar, /label=\{t\('about\.open'\)\}/);
  assert.match(bar, /<AboutDialog /);
});

test('the About dialog shows version, author, licence, notice and the SLB sentence', () => {
  const dialog = src('shell/AboutDialog.tsx');
  assert.match(dialog, /role="dialog"/);
  assert.match(dialog, /aria-modal="true"/);
  assert.match(dialog, /__APP_VERSION__/);
  for (const key of ['about.title', 'about.author', 'about.license', 'about.licenseName', 'about.notice', 'about.slb', 'shell.close']) {
    assert.match(dialog, new RegExp(`t\\('${key.replace('.', '\\.')}'`), key);
  }
  // Escape and the close button both close it, and focus goes back to what opened it.
  assert.match(dialog, /event\.key === 'Escape'/);
  assert.match(dialog, /returnFocus/);
  assert.doesNotMatch(dialog, /border-left:\s*[2-9]px/);
});

test('while About is open no shortcut, palette or other dialog can open over or behind it', () => {
  const hook = src('shell/useWorkbenchCommands.ts');
  const guard = hook.indexOf('if (isAboutOpen()) return;');
  assert.ok(guard > 0, 'the keydown handler checks About first');
  assert.ok(guard < hook.indexOf("if (id === 'open-palette') {"), 'before the palette toggle');
});

test('About keeps focus inside, returns it even when the opener is gone, and fits short windows', () => {
  const dialog = src('shell/AboutDialog.tsx');
  assert.match(dialog, /event\.key === 'Tab'/);
  assert.match(dialog, /isConnected/);
  // From the palette, the palette is gone before About mounts, so the "opener" is the page body (PVT D1).
  assert.match(dialog, /returnFocus !== document\.body/);
  assert.match(dialog, /className="wb-sheet wb-about"/);
  assert.match(src('styles/workbench.css'), /\.wb-about \{[^}]*max-height:[^}]*overflow-y: auto/);
});

test('the SLB sentence claims only what is true: no OLGA program or licence is included', async () => {
  const { translate } = await import('../src/i18n/index.ts');
  // The app's glossary and help text describe OLGA keywords, so "no OLGA data" would be false.
  assert.doesNotMatch(translate('en', 'about.slb'), /model data|no OLGA data/i);
  assert.match(translate('en', 'about.slb'), /no OLGA software or licence/);
  assert.doesNotMatch(translate('ko', 'about.slb'), /모델 데이터/);
});

test('About strings exist in both languages and differ', async () => {
  const { translate } = await import('../src/i18n/index.ts');
  for (const key of KEYS) {
    const ko = translate('ko', key);
    const en = translate('en', key);
    assert.ok(ko && ko.length > 0, `${key} ko`);
    assert.ok(en && en.length > 0, `${key} en`);
    assert.notEqual(ko, en, `${key} is translated`);
    assert.ok(!HANGUL.test(en), `${key} en carries no Hangul`);
  }
  assert.match(translate('en', 'about.slb'), /not affiliated with.*SLB/i);
  assert.match(translate('ko', 'about.slb'), /SLB/);
  assert.match(translate('en', 'about.author'), /Woojin Go/);
  // The SPDX identifier is the same in both languages.
  assert.equal(translate('en', 'about.licenseName'), 'Apache-2.0');
  assert.equal(translate('ko', 'about.licenseName'), 'Apache-2.0');
});
