// N1: the run preview says whether each fluid table matches the .mfl it was made from.
import assert from 'node:assert/strict';
import test from 'node:test';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const row = (state, reason, mfl = 'gas.mfl') => ({ reference: 'fluid.tab', state, reason, mfl });

test('fresh, stale and unknown each render their own words and tone', () => {
  assert.match(r.renderFluidFreshness('en', [row('fresh', 'matches')]), /<strong>Fluid table fluid\.tab<\/strong><em class="pass">Made from gas\.mfl, which has not changed since\.<\/em>/);
  assert.match(r.renderFluidFreshness('en', [row('stale', 'mfl_changed')]), /<em class="warn">gas\.mfl changed after this table was made/);
  const unknown = r.renderFluidFreshness('en', [row('unknown', 'no_record', null)]);
  assert.match(unknown, /<em>Origin unknown: no record of how this table was made\.<\/em>/);
  assert.doesNotMatch(unknown, /class="(pass|warn|fail)"/);
});

test('every unknown reason has English and Korean text', () => {
  for (const reason of ['no_record', 'bad_record', 'table_changed', 'mfl_missing']) {
    for (const locale of ['en', 'ko']) {
      const html = r.renderFluidFreshness(locale, [row('unknown', reason)]);
      assert.doesNotMatch(html, /run\.fluid/, `${locale} ${reason}`);
      assert.match(html, locale === 'en' ? /Origin unknown/ : /출처 모름/, `${locale} ${reason}`);
    }
  }
  assert.match(r.renderFluidFreshness('ko', [row('stale', 'mfl_changed')]), /<strong>유체 표 fluid\.tab<\/strong><em class="warn">표를 만든 뒤 gas\.mfl이\(가\) 바뀌었어요/);
});

test('no rows render nothing', () => {
  assert.equal(r.renderFluidFreshness('en', []), '');
});
