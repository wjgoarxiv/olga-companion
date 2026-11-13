import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const css = () => readFile(new URL('../src/styles/chat-messages.css', import.meta.url), 'utf8');

test('empty Chat desktop start uses a wider command deck instead of a compact starter island', async () => {
  const source = await css();
  assert.match(
    source,
    /@media \(min-width: 761px\)[\s\S]*?\.empty-state\s*\{[\s\S]*?width:\s*min\(1080px,\s*100%\)[\s\S]*?min-height:\s*min\(500px,\s*calc\(100dvh - 270px\)\)[\s\S]*?align-self:\s*stretch/s,
    'desktop empty Chat should occupy the work area, not sit as a narrow top island'
  );
  assert.match(
    source,
    /@media \(min-width: 761px\)[\s\S]*?\.starter-groups\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1\.15fr\) minmax\(0,\s*1fr\) minmax\(0,\s*0\.95fr\)[\s\S]*?min-height:\s*280px/s,
    'desktop starter groups should form a stable, asymmetric command deck'
  );
  assert.match(
    source,
    /@media \(min-width: 761px\)[\s\S]*?\.starter-list\s*\{[\s\S]*?grid-auto-rows:\s*minmax\(82px,\s*1fr\)[\s\S]*?align-content:\s*stretch/s,
    'desktop starter cards should stretch to use the deck height'
  );
});
