// Hyper-real round 11 (2026-11-11, Korean UI): the model checked whether a table file
// existed and the failed card read "input file not found: 'hr11_air_water.tab'" in English.
// The backend message stays English for the model; the card localizes the common ones.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { toolErrorText } from '../src/toolErrorText.ts';

test('a missing input or result file reads in Korean with its name', () => {
  assert.equal(toolErrorText("input file not found: 'hr11_air_water.tab'", 'ko'), "파일을 찾을 수 없습니다: 'hr11_air_water.tab'");
  assert.equal(toolErrorText("result file not found: 'case.tpl'", 'ko'), "결과 파일을 찾을 수 없습니다: 'case.tpl'");
});

// Round 12: a results_series call without a position failed with this English sentence.
test('a series that could not be read names the variable and file in Korean', () => {
  assert.equal(
    toolErrorText("Could not read a series for 'PT' from case.tpl.", 'ko'),
    "case.tpl에서 'PT' 시계열을 읽지 못했습니다.",
  );
  assert.equal(
    toolErrorText("Could not read a series for 'PT' from case.tpl.", 'en'),
    "Could not read a series for 'PT' from case.tpl.",
  );
});

test('English keeps the backend sentence; in Korean an unknown error is labelled as the English original', () => {
  assert.equal(toolErrorText("input file not found: 'a.tab'", 'en'), "File not found: 'a.tab'");
  assert.equal(toolErrorText('Something else went wrong.', 'en'), 'Something else went wrong.');
  assert.equal(toolErrorText('Something else went wrong.', 'ko'), '도구 오류(영문 원문): Something else went wrong.');
  assert.equal(toolErrorText('미실행: 승인을 먼저 받아야 합니다.', 'ko'), '미실행: 승인을 먼저 받아야 합니다.');
});

test('every not-found message the path layer raises is localized', async () => {
  const source = await readFile(new URL('../../src/olga_companion/workspace_paths.py', import.meta.url), 'utf8');
  const prefixes = [...source.matchAll(/f"([a-z ]+ not found): /g)].map((m) => m[1]);
  assert.ok(prefixes.length >= 2, `collected ${prefixes.length} not-found messages`);
  for (const prefix of prefixes) {
    assert.doesNotMatch(toolErrorText(`${prefix}: 'x'`, 'ko'), /not found/, prefix);
  }
});

test('the tool card shows the failure through toolErrorText', async () => {
  const card = await readFile(new URL('../src/ToolUnit.tsx', import.meta.url), 'utf8');
  assert.match(card, /toolErrorText\(/);
});
