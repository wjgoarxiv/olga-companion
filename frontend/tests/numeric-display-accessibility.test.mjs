import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('significant-figure picker exposes one concise name and its display-only consequence', async () => {
  const [settings, ko] = await Promise.all([
    read('../src/SettingsView.tsx'),
    read('../src/i18n/ko.ts'),
  ]);

  assert.match(settings, /id="significant-figures"/, 'the control has a stable label target');
  assert.match(
    settings,
    /<label[^>]*htmlFor="significant-figures"[^>]*>[\s\S]*?<span>\{t\('settings\.significantFigures'\)\}<\/span>[\s\S]*?<\/label>/,
    'the visible label names only the setting rather than concatenating every option',
  );
  assert.match(
    settings,
    /<select[\s\S]*?id="significant-figures"[\s\S]*?aria-describedby="numeric-display-description"/,
    'the picker is described by the display-only consequence',
  );
  assert.match(settings, /\{t\('settings\.numericNote'\)\}/, 'the consequence note reads from the dictionary');
  assert.match(
    ko,
    /'settings\.numericNote': '내보내는 원본은 그대로 두고 결과 표·차트·요약의 자릿수만 둥글게 표시합니다\.'/,
  );
});

test('significant-figure picker meets the mobile touch standard used by the other Settings selectors', async () => {
  const css = await read('../src/styles/settings.css');

  assert.match(
    css,
    /@media \(max-width:\s*760px\)[\s\S]*?\.numeric-display-control select\s*\{[^}]*min-height:\s*44px/s,
  );
});
