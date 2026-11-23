// 0.1.27: English that still showed in the Korean UI (result history labels, the receipt fallback,
// the case chip and sweep-add aria-labels) goes through the locale files.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { filterResultFiles, historicalResultLabel, resultContextLabel } from '../src/resultPresentation.ts';
import { translate } from '../src/i18n/index.ts';

const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');
const hangul = /[가-힣]/;
const run = (extra) => ({ id: 'r1', name: 'case.tpl', rel: 'abc/case.tpl', origin: 'run', run_id: 'abc', lineage_status: null, ...extra });

test('result context labels follow the locale and keep the run or file identity', () => {
  const cases = [run({}), run({ lineage_status: 'receipt_changed' }), { ...run({}), origin: 'workspace', rel: 'out/case.tpl' }];
  for (const result of cases) {
    const ko = resultContextLabel(result, 'ko');
    const en = resultContextLabel(result, 'en');
    assert.match(ko, hangul, `ko label for ${result.origin}/${result.lineage_status}`);
    assert.doesNotMatch(ko, /Historical|Run |Workspace package|changed after/, 'no English words in the ko label');
    assert.match(ko, result.origin === 'run' ? /abc/ : /out\/case\.tpl/);
    assert.match(en, result.origin === 'run' ? /abc/ : /out\/case\.tpl/);
  }
  assert.match(historicalResultLabel('abc', 'en'), /^Historical · Run abc · /);
  assert.match(resultContextLabel(run({ lineage_status: 'receipt_changed' }), 'en'), /Run abc · changed after the run · not verified/);
  assert.match(resultContextLabel({ ...run({}), origin: 'workspace', rel: 'out/case.tpl' }, 'en'), /Workspace package result · out\/case\.tpl/);
});

test('result search matches the label in either language', () => {
  const results = [run({})];
  assert.equal(filterResultFiles(results, 'historical').length, 1);
  assert.equal(filterResultFiles(results, translate('ko', 'results.context.historicalWord')).length, 1);
});

test('the views pass the locale and no English label text stays in the source', () => {
  const presentation = src('resultPresentation.ts');
  assert.doesNotMatch(presentation, /`Historical · Run|'ance unavailable'|`Workspace package result|changed after the run/);
  assert.match(src('ResultsLayout.tsx'), /resultContextLabel\(selected, locale\)/);
  const rail = src('ResultsInventoryRail.tsx');
  assert.match(rail, /resultContextLabel\(f, locale\)/);
  assert.doesNotMatch(rail, /`Run \$\{/);
  assert.doesNotMatch(src('WorkspaceBar.tsx'), /aria-label=\{activeName \? `Active case/);
  assert.doesNotMatch(src('SweepValueBuilder.tsx'), /aria-label="Add sweep value"/);
});

test('the new keys exist in both locales', () => {
  for (const key of ['results.context.historical', 'results.context.changed', 'results.context.workspace', 'results.context.run', 'results.context.receipt', 'results.context.historicalWord', 'sweep.addValueAria']) {
    assert.notEqual(translate('ko', key), key, `ko ${key}`);
    assert.notEqual(translate('en', key), key, `en ${key}`);
  }
});
