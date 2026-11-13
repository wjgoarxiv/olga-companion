import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('(10) editing any findings field clears the shown verdicts', async () => {
  const panel = await read('../src/FindingsPanel.tsx');
  const onFieldStart = panel.indexOf('function onField');
  const onField = panel.slice(onFieldStart, panel.indexOf('function onKindChange', onFieldStart));
  assert.match(onField, /setVerdict\(null\)/, 'a field edit drops the shown verdict');
  assert.match(onField, /setShownVerdicts\(\[\]\)/, 'a field edit drops the verdict list used by the report');
  const genkeyStart = panel.indexOf('function onGenkeyChange');
  assert.notEqual(genkeyStart, -1, 'the case-file field has its own change handler');
  const genkeyHandler = panel.slice(genkeyStart, panel.indexOf('function criterionParams', genkeyStart));
  assert.match(genkeyHandler, /setVerdict\(null\)/, 'a case-file edit drops the shown verdict');
  assert.match(genkeyHandler, /setShownVerdicts\(\[\]\)/, 'a case-file edit drops the verdict list used by the report');
  assert.match(panel, /onChange=\{\(event\) => onGenkeyChange\(event\.target\.value\)\}/, 'the case-file input uses the clearing handler');
});
