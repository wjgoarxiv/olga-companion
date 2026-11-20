// L3: the CSV export has an opt-in "For Excel" box that asks the backend for a UTF-8 BOM.
import assert from 'node:assert/strict';
import test from 'node:test';
import { resultAnalysisRenderer } from './helpers/render-result-analysis.mjs';

const r = await resultAnalysisRenderer();

test('the For Excel box renders unchecked by default, in English and Korean', () => {
  const en = r.renderAnalysis('en', { csvExcelBom: false, setCsvExcelBom: () => {} });
  assert.match(en, /<label class="result-csv-excel" title="Adds a UTF-8 BOM[^"]*"><input type="checkbox"\/><span>For Excel<\/span><\/label>/);
  const ko = r.renderAnalysis('ko', { csvExcelBom: true, setCsvExcelBom: () => {} });
  assert.match(ko, /<input type="checkbox" checked=""\/><span>엑셀용<\/span>/);
});

test('without a setter the box is not shown', () => {
  assert.doesNotMatch(r.renderAnalysis('en', {}), /result-csv-excel/);
});

function captureFetch() {
  const bodies = [];
  globalThis.window ??= { location: { hostname: 'localhost', protocol: 'http:' } };
  globalThis.fetch = async (_url, init) => {
    bodies.push(JSON.parse(init.body));
    return new Response(JSON.stringify({ ok: true, csv: 'x.csv' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  return bodies;
}

test('the request carries excel_bom only when the box is on', async () => {
  const bodies = captureFetch();
  await r.exportSelectedCsv('run:a/case.tpl', 'PT', 'B');
  await r.exportSelectedCsv('run:a/case.tpl', 'PT', 'B', undefined, true);
  await r.exportProfileCsv('run:a/case.ppl', 'HOL', 'MAIN', 60);
  await r.exportProfileCsv('run:a/case.ppl', 'HOL', 'MAIN', undefined, true);
  assert.deepEqual(bodies, [
    { path: 'run:a/case.tpl', variables: ['PT'], position: 'B' },
    { path: 'run:a/case.tpl', variables: ['PT'], position: 'B', excel_bom: true },
    { path: 'run:a/case.ppl', variables: ['HOL'], branch: 'MAIN', timestep: 60 },
    { path: 'run:a/case.ppl', variables: ['HOL'], branch: 'MAIN', excel_bom: true },
  ]);
});
