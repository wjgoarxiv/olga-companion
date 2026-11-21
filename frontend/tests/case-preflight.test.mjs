import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { orderedItems, rowOpener } from '../src/casePreflightModel.mjs';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

/* 0.1.22 row 8: the pre-run check step lists the file checks the app already makes. Each item that
 * names an edit-table row opens that row; the list says it is a file check, not a simulation. */

const ITEMS = [
  { id: 'validation', state: 'ok', message_code: 'validation_clean' },
  { id: 'pvt:OUTLET:pressure', state: 'warn', message_code: 'pvt_outside', row_id: 'nodes.OUTLET.pressure_pa', target: 'OUTLET' },
  { id: 'row:integration.max_dt_s', state: 'missing', message_code: 'value_unset', row_id: 'integration.max_dt_s', target: 'MAXDT', field: 'max_dt_s' },
];

test('items read missing first, then warnings, then passes, keeping server order inside a state', () => {
  assert.deepEqual(orderedItems(ITEMS).map((item) => item.id), ['row:integration.max_dt_s', 'pvt:OUTLET:pressure', 'validation']);
  assert.deepEqual(orderedItems([{ id: 'x', state: 'odd', message_code: 'a' }]).map((item) => item.id), ['x']);
});

test('an item with a row opens that row of this case; one without has no action', () => {
  const opened = [];
  const open = rowOpener('cases/a.genkey', ITEMS[2], (rel, rowId) => opened.push([rel, rowId]));
  open();
  assert.deepEqual(opened, [['cases/a.genkey', 'integration.max_dt_s']]);
  assert.equal(rowOpener('cases/a.genkey', ITEMS[0], () => {}), null);
});

for (const locale of ['ko', 'en']) {
  test(`${locale}: the list is labelled a file check and names each item`, async () => {
    const { renderCasePreflightList } = await reviewNotesRenderer();
    const html = renderCasePreflightList(locale, ITEMS);
    assert.match(html, locale === 'ko' ? /파일 점검, 시뮬레이션 아님/ : /File check, not a simulation/);
    assert.match(html, /OUTLET/);
    assert.match(html, /MAXDT/);
    assert.equal((html.match(/<button/g) ?? []).length, 2, 'one open-row button per item that has a row');
    assert.doesNotMatch(html, /<input/, 'the list fills in nothing');
  });
}

test('review: a fluid-range value reads in bar like the sweep preview, and each open button names its row', async () => {
  const { renderCasePreflightList } = await reviewNotesRenderer();
  const values = { origin: 'OUTLET', quantity: 'pressure', value: '9500000 PA', status: 'outside', relation: 'below' };
  const pvt = { id: 'pvt:OUTLET:pressure', state: 'warn', message_code: 'pvt_outside', row_id: 'nodes.OUTLET.pressure_pa', target: 'OUTLET', values };
  const html = renderCasePreflightList('en', [pvt, { id: 'row:x', state: 'missing', message_code: 'value_unset', row_id: 'integration.max_dt_s', target: 'MAXDT', field: 'max_dt_s' }]);
  assert.match(html, /95 bar/);
  assert.doesNotMatch(html, /\(MAXDT\) \(MAXDT\)/, 'the keyword is named once');
  assert.doesNotMatch(html.replace(/<[^>]+>/g, ' '), /\bPA\b/);
  const ids = [...html.matchAll(/<span class="case-preflight-text" id="([^"]+)"/g)].map((m) => m[1]);
  const described = [...html.matchAll(/<button[^>]*aria-describedby="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(described.length, 2);
  assert.deepEqual(described.sort(), ids.sort(), 'each button points at its own item text');
});

test('review: a validator that did not finish has its own sentence', async () => {
  const { renderCasePreflightList } = await reviewNotesRenderer();
  assert.match(renderCasePreflightList('ko', [{ id: 'validation', state: 'warn', message_code: 'validation_unavailable' }]), /검사기가 끝나지 않아/);
});

test('an unknown message code still shows, marked as not translated', async () => {
  const { renderCasePreflightList } = await reviewNotesRenderer();
  const html = renderCasePreflightList('ko', [{ id: 'new', state: 'warn', message_code: 'brand_new_rule' }]);
  assert.match(html, /번역되지 않은 메시지/);
  assert.match(html, /brand_new_rule/);
});

test('PVT D1: in the narrow step guide the open button sits under the sentence, so the sentence keeps its width', async () => {
  const css = await readFile(new URL('../src/styles/simulation-guide.css', import.meta.url), 'utf8');
  assert.match(css, /\.case-preflight-item \{[^}]*grid-template-columns: max-content minmax\(0, 1fr\);/);
  assert.match(css, /\.case-preflight-open \{[^}]*grid-column: 2 \/ -1;[^}]*justify-self: start;/);
});

test('PVT D3: opening a row from the check closes the step guide, so the opened row is not covered', async () => {
  const bar = await readFile(new URL('../src/shell/StepBar.tsx', import.meta.url), 'utf8');
  assert.match(bar, /addEventListener\(OPEN_CASE_EDIT_EVENT, close\)/);
});

test('the check step shows the list for the selected case and leaves the run approval alone', async () => {
  const guide = await readFile(new URL('../src/SimulationGuide.tsx', import.meta.url), 'utf8');
  assert.match(guide, /step\.id === 'validate' && props\.activeCaseRel && \(/);
  const list = await readFile(new URL('../src/CasePreflight.tsx', import.meta.url), 'utf8');
  assert.match(list, /'\/api\/case-preflight\?rel='/);
  assert.doesNotMatch(list, /api\/run\/|approvals/);
});
