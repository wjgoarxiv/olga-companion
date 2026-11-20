// N2: warn-only case checks in the run preview, and which keys the app can change.
import assert from 'node:assert/strict';
import test from 'node:test';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const RULES = {
  endtime_missing: {},
  mindt_above_maxdt: { value: 5, limit: 1, unit: 's' },
  dtstart_above_maxdt: { value: 200, limit: 100, unit: 's' },
  dtplot_above_endtime: { value: 60, limit: 0.0001, unit: 's' },
  diameter_not_positive: { label: 'Pipe_1', value: -0.1524, unit: 'm' },
  segment_not_positive: { label: 'Pipe_2' },
  nsegment_mismatch: { label: 'P1', value: 3, limit: 2 },
  roughness_vs_diameter: { label: 'P1', value: 0.02, limit: 0.2, unit: 'm' },
};

test('every rule renders its values in English and Korean, never a raw key', () => {
  for (const [rule, values] of Object.entries(RULES)) {
    for (const locale of ['en', 'ko']) {
      const html = r.renderLint(locale, [{ rule, keyword: 'TREND', values }]);
      assert.doesNotMatch(html, /lint\.|\{(value|limit|label|keyword)\}/, `${locale} ${rule}`);
      if (values.label) assert.match(html, new RegExp(values.label), `${locale} ${rule}`);
      if (values.value !== undefined) assert.match(html, new RegExp(String(values.value).replace('.', '\\.')), `${locale} ${rule}`);
    }
  }
});

test('each rule puts the value and the limit in their own places (review)', () => {
  const expected = {
    mindt_above_maxdt: ['MINDT (5 s) is larger than MAXDT (1 s).', 'MINDT(5 s)가 MAXDT(1 s)보다 커요.'],
    dtstart_above_maxdt: ['DTSTART (200 s) is larger than MAXDT (100 s).', 'DTSTART(200 s)가 MAXDT(100 s)보다 커요.'],
    dtplot_above_endtime: ['TREND DTPLOT (60 s) is longer than the whole run (0.0001 s), so it records almost nothing.', 'TREND DTPLOT(60 s)이 전체 실행 시간(0.0001 s)보다 길어서 거의 기록되지 않아요.'],
    diameter_not_positive: ['Pipe Pipe_1: DIAMETER is -0.1524 m; it must be above zero.', '배관 Pipe_1: DIAMETER가 -0.1524 m예요. 0보다 커야 해요.'],
    nsegment_mismatch: ['Pipe P1: NSEGMENT is 3 but LSEGMENT lists 2 lengths.', '배관 P1: NSEGMENT는 3인데 LSEGMENT에는 길이가 2개 있어요.'],
    roughness_vs_diameter: ['Pipe P1: ROUGHNESS (0.02 m) is more than 5% of DIAMETER (0.2 m).', '배관 P1: ROUGHNESS(0.02 m)가 DIAMETER(0.2 m)의 5%보다 커요.'],
  };
  for (const [rule, [en, ko]] of Object.entries(expected)) {
    assert.ok(r.renderLint('en', [{ rule, keyword: 'TREND', values: RULES[rule] }]).includes(`<li>${en}</li>`), `en ${rule}`);
    assert.ok(r.renderLint('ko', [{ rule, keyword: 'TREND', values: RULES[rule] }]).includes(`<li>${ko}</li>`), `ko ${rule}`);
  }
});

test('the checks say they do not stop the run, and none render nothing', () => {
  const html = r.renderLint('en', [{ rule: 'dtplot_above_endtime', keyword: 'PROFILE', values: RULES.dtplot_above_endtime }]);
  assert.match(html, /role="note"/);
  assert.match(html, /do not stop the run/);
  assert.match(html, /PROFILE DTPLOT \(60 s\) is longer than the whole run \(0\.0001 s\)/);
  assert.match(r.renderLint('ko', [{ rule: 'endtime_missing', keyword: 'INTEGRATION', values: {} }]), /실행을 막지는 않아요/);
  assert.equal(r.renderLint('en', []), '');
});

test('the coverage map names every key in its group with a count', () => {
  const coverage = { table: ['VALVE.OPENING'], sweep: ['INTEGRATION.MAXDT', 'PIPE.ROUGHNESS'], fixed: [] };
  const html = r.renderCoverage('en', coverage);
  assert.match(html, /<details class="case-edit-coverage">/);
  assert.match(html, /data-group="table"><strong>Change in this table, saved as a reviewed new copy \(1\)<\/strong><p><code>VALVE\.OPENING<\/code><\/p>/);
  assert.match(html, /as separate copies \(2\)/);
  assert.match(html, /more than once \(0\)<\/strong><\/div>/);
  assert.match(r.renderCoverage('ko', coverage), /스윕에서만 바꿔 별도 사본으로 실행 \(2\)/);
});
