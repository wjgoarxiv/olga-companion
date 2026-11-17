import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';
import {
  TAB_IMPORT_ISSUE_CODES,
  importRequest,
  isTabFileName,
  issueText,
  parseFraction,
  suggestedLabel,
  suggestedTabName,
} from '../src/tabImport.ts';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const render = await approvalCardRenderer();
const translator = (locale) => (key, vars) => {
  const dict = locale === 'en' ? en : ko;
  const template = dict[key] ?? key;
  return vars ? template.replace(/\{(\w+)\}/g, (m, name) => (vars[name] === undefined ? m : String(vars[name]))) : template;
};

test('a label and a new table name are suggested from the picked file', () => {
  assert.equal(suggestedLabel('lab/Fluid A (run 2).csv'), 'Fluid_A_run_2');
  assert.equal(suggestedLabel('2024.xlsx'), 'FLUID_2024');
  assert.equal(suggestedLabel('.csv'), 'FLUID');
  assert.equal(suggestedTabName('lab/props.csv'), 'lab/props.tab');
  assert.equal(suggestedTabName('props.xlsx'), 'props.tab');
});

test('the new table name must be a plain relative .tab path', () => {
  for (const good of ['props.tab', 'lab/props.tab', ' props.TAB ']) assert.equal(isTabFileName(good), true, good);
  for (const bad of ['', 'props', 'props.csv', '../props.tab', 'a/../b.tab', '/abs/props.tab', 'a\\b.tab', '.tab']) {
    assert.equal(isTabFileName(bad), false, bad);
  }
});

test('the water fraction field only accepts a number from 0 to 1', () => {
  assert.equal(parseFraction(''), null);
  assert.equal(parseFraction('abc'), null);
  assert.equal(parseFraction('1.2'), null);
  assert.equal(parseFraction('0.4'), 0.4);
  assert.equal(parseFraction('0'), 0);
});

test('the chat request names the table, the file and the label, and says nothing is calculated', () => {
  const input = { source: 'lab/props.csv', tab: 'lab/props.tab', label: 'FLUID_A', waterFraction: null };
  const en1 = importRequest(translator('en'), input);
  assert.match(en1, /lab\/props\.csv/);
  assert.match(en1, /lab\/props\.tab/);
  assert.match(en1, /FLUID_A/);
  assert.match(en1, /as given/);
  assert.match(en1, /nothing is calculated/i);
  assert.doesNotMatch(en1, /total water fraction/i);
  const withWater = importRequest(translator('en'), { ...input, waterFraction: 0.4 });
  assert.match(withWater, /total water fraction 0\.4/i);
  const ko1 = importRequest(translator('ko'), input);
  assert.match(ko1, /그대로/);
  assert.match(ko1, /계산/);
});

test('every known issue code has its own sentence in both languages', () => {
  assert.ok(TAB_IMPORT_ISSUE_CODES.length >= 15);
  for (const code of TAB_IMPORT_ISSUE_CODES) {
    const key = `tabImport.issue.${code}`;
    assert.equal(typeof en[key], 'string', `en ${key}`);
    assert.equal(typeof ko[key], 'string', `ko ${key}`);
    assert.notEqual(en[key], ko[key], `${key} is translated`);
  }
});

test('issue text uses the translated sentence with its parameters, and falls back to the reason', () => {
  const t = translator('en');
  const missing = issueText(t, {
    code: 'missing_point', row: null, reason: 'raw reason', params: { count: 2, first: [500000, 10] },
  });
  assert.match(missing, /2/);
  assert.match(missing, /500000/);
  assert.doesNotMatch(missing, /raw reason/);
  const axis = issueText(t, { code: 'axis_not_increasing', row: null, reason: 'raw', params: { axis: 'temperature' } });
  assert.match(axis, /temperature/i);
  assert.equal(issueText(t, { code: 'validator_error', row: null, reason: 'V020: bad density', params: {} }), 'V020: bad density');
  assert.match(issueText(t, { code: 'not_a_number', row: 7, reason: 'raw', params: { column: 'ROG' } }), /7/);
});

test('the fluid table flow renders the import panel and the panel only previews and asks for the approved save', async () => {
  const [flow, panel, api] = await Promise.all([
    read('../src/shell/FluidTableFlow.tsx'),
    read('../src/shell/TabImportPanel.tsx'),
    read('../src/tabImportApi.ts'),
  ]);
  assert.match(flow, /import TabImportPanel from '\.\/TabImportPanel'/);
  assert.match(flow, /<TabImportPanel/);
  assert.match(panel, /tabImportPreview\(/);
  assert.match(panel, /listPipeTables\(/);
  assert.match(panel, /props\.chat\.setInput\(importRequest\(/);
  assert.match(panel, /props\.onOpenDock\(\)/);
  assert.match(panel, /disabled=\{!ready/);
  assert.match(api, /\/api\/fluids\/tab-import\/preview/);
  assert.doesNotMatch(panel + api, /tab-import\/(write|save|create)/);
  assert.doesNotMatch(panel, /fetch\(|apiFetch/);
});

test('the panel copy says the values are written as given and nothing is calculated, in both languages', () => {
  assert.match(en['tabImport.subtitle'], /as given/);
  assert.match(en['tabImport.subtitle'], /nothing is calculated/i);
  assert.match(ko['tabImport.subtitle'], /그대로/);
  assert.match(ko['tabImport.subtitle'], /계산/);
  assert.doesNotMatch(`${en['tabImport.subtitle']} ${ko['tabImport.subtitle']}`, /hysys/i, 'shipped text names no other vendor product');
  assert.match(en['tabImport.units'], /kg\/m3/);
  assert.notEqual(en['tabImport.title'], ko['tabImport.title']);
});

test('the approval card for the import shows the grid and the as-given note, in English and Korean', () => {
  const row = (key, value, unit) => (unit === undefined ? { key, value } : { key, value, unit });
  const KIND = {
    en: 'Values written as given from your own table; nothing is calculated. Check that the units and the range fit your case.',
    ko: '내가 가진 표의 값을 그대로 옮겨 쓴 표입니다. 계산한 값은 없습니다. 단위와 범위가 내 사례에 맞는지 확인하세요.',
  };
  const request = (locale) => ({
    name: 'fluids_import_tab',
    call_id: 'call_import',
    pending_id: 'pending_import',
    args: { source_rel: 'props.csv', tab_rel: 'props.tab', fluid_label: 'FLUID_A' },
    display: {
      fields: [
        row('file', 'props.tab'), row('source_file', 'props.csv'), row('label', 'FLUID_A'),
        row('pressure_points', '3'), row('temperature_points', '2'), row('point_count', '6'),
        row('columns', 'ROG, ROHL'), row('pressure_range', '100000 – 1000000', 'Pa'),
        row('temperature_range', '10 – 30', 'degC'), row('table_kind', KIND[locale]),
      ],
    },
  });
  const htmlEn = render('en', request('en'));
  for (const text of ['props.tab', 'props.csv', 'FLUID_A', 'ROG, ROHL', '100000 – 1000000 Pa', KIND.en]) {
    assert.ok(htmlEn.includes(text), `en card shows ${text}`);
  }
  assert.match(htmlEn, /Approval needed — Write the .tab from your table/);
  assert.match(htmlEn, /Approve and write the file/);
  assert.doesNotMatch(htmlEn, /fluids_import_tab/i);
  assert.doesNotMatch(htmlEn, /sandbox/i);
  const htmlKo = render('ko', request('ko'));
  assert.ok(htmlKo.includes(KIND.ko));
  assert.match(htmlKo, /승인 필요 — 내 표로 .tab 만들기/);
  assert.doesNotMatch(htmlKo, /fluids_import_tab/i);
});

test('the panel style uses only tokens, 44px targets, small text of at least 12px and no endless animation', async () => {
  const css = await read('../src/styles/tab-import.css');
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/, 'no hard-coded colours');
  assert.doesNotMatch(css, /animation|@keyframes/);
  assert.doesNotMatch(css, /font-size:\s*\d+px/, 'font sizes come from tokens');
  assert.match(css, /min-height: var\(--tgt\)/);
  const styles = await read('../src/styles.css');
  assert.match(styles, /@import '\.\/styles\/tab-import\.css';/);
});
