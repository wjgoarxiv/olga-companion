// N5: two workspace cases compared key by key, read-only.
import assert from 'node:assert/strict';
import test from 'node:test';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const base = { a: 'cases/valve.genkey', b: 'cases/valve.edit1.genkey', truncated: false, removed: [], added: [] };

test('changed values show where, the key and both values under the two file names', () => {
  const html = r.renderCaseDiff('en', {
    ...base, same: false,
    changed: [
      { component: 'OUTLET', keyword: 'PARAMETERS', label: 'OUTLET', key: 'PRESSURE', before: '200000 Pa', after: '500000 Pa' },
      { component: null, keyword: 'INTEGRATION', label: '#1', key: 'MAXDT', before: null, after: '10 s' },
    ],
  });
  assert.match(html, /<caption>Changed values \(2\)<\/caption>/);
  assert.match(html, /<th scope="col">valve\.genkey<\/th><th scope="col">valve\.edit1\.genkey<\/th>/);
  assert.match(html, /<td>OUTLET · PARAMETERS OUTLET<\/td><td><code>PRESSURE<\/code><\/td><td>200000 Pa<\/td><td>500000 Pa<\/td>/);
  assert.match(html, /<td>INTEGRATION #1<\/td><td><code>MAXDT<\/code><\/td><td><em>not set<\/em><\/td><td>10 s<\/td>/);
});

test('records only in one case are listed under its name', () => {
  const html = r.renderCaseDiff('ko', {
    ...base, same: false, changed: [],
    removed: [{ component: 'MAIN', keyword: 'POSITION', label: 'POS_MAIN_1' }],
    added: [{ component: null, keyword: 'MATERIAL', label: 'STEEL' }],
  });
  assert.match(html, /valve\.genkey에만 있음 \(1\):<\/strong> MAIN · POSITION POS_MAIN_1/);
  assert.match(html, /valve\.edit1\.genkey에만 있음 \(1\):<\/strong> MATERIAL STEEL/);
  assert.doesNotMatch(html, /<table/);
});

test('the same cases say so and that formatting is not compared', () => {
  assert.match(r.renderCaseDiff('en', { ...base, same: true, changed: [] }), /role="status">The two cases set the same values\. Comments, line breaks and key order are not compared\./);
  assert.match(r.renderCaseDiff('en', { ...base, same: false, changed: [], added: [{ component: null, keyword: 'X', label: '#1' }], truncated: true }), /first 400 differences/);
});

test('records without a label keep their order number, so two of them read apart (review)', () => {
  const html = r.renderCaseDiff('en', {
    ...base, same: false,
    changed: [
      { component: null, keyword: 'TREND', label: '#1', key: 'DTPLOT', before: '10 s', after: '20 s' },
      { component: null, keyword: 'TREND', label: '#2', key: 'DTPLOT', before: '30 s', after: '40 s' },
    ],
    removed: [{ component: null, keyword: 'TREND', label: '#3' }, { component: null, keyword: 'TREND', label: '#4' }],
  });
  assert.match(html, /<td>TREND #1<\/td>.*<td>TREND #2<\/td>/s);
  assert.match(html, /\(2\):<\/strong> TREND #3, TREND #4/);
});

test('two cases with the same file name are told apart by their folders (review)', () => {
  const html = r.renderCaseDiff('en', { ...base, a: 'sweep/a/case.genkey', b: 'sweep/b/case.genkey', same: false, changed: [
    { component: null, keyword: 'INTEGRATION', label: '#1', key: 'ENDTIME', before: '1 h', after: '2 h' },
  ], added: [{ component: null, keyword: 'X', label: 'Y' }] });
  assert.match(html, /<th scope="col">sweep\/a\/case\.genkey<\/th><th scope="col">sweep\/b\/case\.genkey<\/th>/);
  assert.match(html, /Only in sweep\/b\/case\.genkey/);
});
