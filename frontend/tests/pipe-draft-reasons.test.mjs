import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { translate } from '../src/i18n/index.ts';
import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

const legacy = JSON.parse(await read('./fixtures/pipe-issue-codes.json'));
const endpoints = JSON.parse(await read('./fixtures/pipe-endpoint-issue-codes.json'));
const readRefusals = JSON.parse(await read('./fixtures/pipe-read-refusal-codes.json'));
assert.ok(legacy.length > 0, 'the lane-BE registry is read');
assert.ok(endpoints.length > 0, 'the lane-EP registry is read');
assert.ok(readRefusals.length > 0, 'the read-refusal registry is read');
const codes = [...legacy, ...endpoints, ...readRefusals];

test('FER3: every registry code has ko and en reason keys', () => {
  assert.equal(codes.length, 69, 'the registry size is pinned, not a threshold');
  for (const code of codes) {
    const key = `pipeDraft.reason.${code}`;
    assert.ok(key in ko, `ko has ${key}`);
    assert.ok(key in en, `en has ${key}`);
    assert.notEqual(ko[key], key);
    assert.notEqual(en[key], key);
    assert.notEqual(ko[key], en[key], `${key} is translated, not copied`);
    assert.match(ko[key], /[가-힣]/, `${key} is Korean in ko`);
    assert.doesNotMatch(en[key], /[가-힣]/, `${key} en carries no Hangul`);
    assert.deepEqual(placeholders(ko[key]), placeholders(en[key]), `${key} keeps the same placeholders`);
  }
});

test('FER3: the spec pattern key renders the carried reason', () => {
  for (const dictionary of [ko, en]) assert.ok('pipeDraft.reason.spec' in dictionary);
  assert.deepEqual(placeholders(ko['pipeDraft.reason.spec']), ['reason']);
  assert.deepEqual(placeholders(en['pipeDraft.reason.spec']), ['reason']);
});

test('FER3: a coded issue formats in the app language with its params', async () => {
  const { formatDraftReason } = await import('../src/pipeTableDraft.ts');
  const t = (key, vars) => translate('ko', key, vars);
  const missing = formatDraftReason(
    { row: 4, field: 'diameter_m', reason: 'value is missing', code: 'value_missing', params: { field: 'diameter_m' } },
    t,
  );
  assert.match(missing, /diameter_m/);
  assert.match(missing, /[가-힣]/);
  const caps = formatDraftReason(
    { row: null, field: 'caps', reason: 'too big', code: 'table_over_caps', params: { caps: 'nodes, sections' } },
    (key, vars) => translate('en', key, vars),
  );
  assert.match(caps, /nodes, sections/);
});

test('FER3: an unknown code falls back to the English reason', async () => {
  const { formatDraftReason } = await import('../src/pipeTableDraft.ts');
  const t = (key, vars) => translate('ko', key, vars);
  assert.equal(
    formatDraftReason({ row: 1, field: 'x', reason: 'some future problem', code: 'not_a_code_yet', params: {} }, t),
    'some future problem',
  );
  assert.equal(
    formatDraftReason({ row: 1, field: 'x', reason: 'some future problem', code: '', params: {} }, t),
    'some future problem',
  );
});

test('FER4-M2: a spec reason shows without its code token', async () => {
  const { formatDraftReason } = await import('../src/pipeTableDraft.ts');
  const rendered = formatDraftReason(
    { row: null, field: 'pressure', reason: 'spec.invalid_geometry: bad', code: 'spec.invalid_geometry', params: {} },
    (key, vars) => translate('en', key, vars),
  );
  assert.doesNotMatch(rendered, /invalid_geometry/);
  assert.match(rendered, /bad/);
});

test('FER3: the card renders the formatted reason, never the raw field', async () => {
  const card = await read('../src/PipeTableDraftCard.tsx');
  assert.match(card, /formatDraftReason/, 'the issue reason goes through the formatter');
  assert.doesNotMatch(card, /\{issue\.reason\}/, 'no raw reason reaches the card');
});

test('FER4-H1: the boundary degree sentence states facts, not needs', async () => {
  const { formatDraftReason } = await import('../src/pipeTableDraft.ts');
  const issue = {
    row: 9, field: 'SRC', reason: 'a source needs 1 outgoing and 0 incoming flowpaths',
    code: 'boundary_bad_degree', params: { node: 'SRC', kind: 'source', incoming: 0, outgoing: 1 },
  };
  const en = formatDraftReason(issue, (key, vars) => translate('en', key, vars));
  assert.match(en, /SRC is a source but has 1 outgoing and 0 incoming flowpaths/);
  assert.doesNotMatch(en, /needs/);
  const ko = formatDraftReason(issue, (key, vars) => translate('ko', key, vars));
  assert.match(ko, /SRC/);
  assert.match(ko, /나가는 흐름/);
  assert.match(ko, /들어오는 흐름/);
  assert.doesNotMatch(ko, /필요해요/);
});

test('FER4-M1: a missing or null param falls back to the reason', async () => {
  const { formatDraftReason, presentPipeDraft } = await import('../src/pipeTableDraft.ts');
  const t = (key, vars) => translate('ko', key, vars);
  assert.equal(
    formatDraftReason(
      { row: 4, field: 'diameter_m', reason: 'value is missing', code: 'value_missing', params: {} },
      t,
    ),
    'value is missing',
  );
  const view = presentPipeDraft('pipe_table_import', {
    created: false,
    issue_count: 1,
    issues: [{ row: 4, field: 'diameter_m', reason: 'value is missing', code: 'value_missing', params: { field: null } }],
  });
  assert.deepEqual(view.issues[0].params, {});
  assert.equal(formatDraftReason(view.issues[0], t), 'value is missing');
});

test('FER4-L1: the rendered card states facts in ko and en', async () => {
  const { draftCardRenderer } = await import('./helpers/render-draft-card.mjs');
  const render = await draftCardRenderer();
  const { presentPipeDraft } = await import('../src/pipeTableDraft.ts');
  const payload = {
    created: false,
    issue_count: 1,
    issues: [{
      row: 9, field: 'SRC', reason: 'a source needs 1 outgoing and 0 incoming flowpaths',
      code: 'boundary_bad_degree', params: { node: 'SRC', kind: 'source', incoming: 0, outgoing: 1 },
    }],
  };
  const koHtml = render('ko', presentPipeDraft('pipe_table_import', payload));
  assert.match(koHtml, /SRC/);
  assert.match(koHtml, /나가는 흐름/);
  assert.doesNotMatch(koHtml, /필요해요/);
  const enHtml = render('en', presentPipeDraft('pipe_table_import', payload));
  assert.match(enHtml, /pipe-draft-issue-reason">SRC is a source but has 1 outgoing and 0 incoming flowpaths\.</);
});

test('table_encrypted refusal renders ko text with no English', async () => {
  const { draftCardRenderer } = await import('./helpers/render-draft-card.mjs');
  const render = await draftCardRenderer();
  const { presentPipeDraft } = await import('../src/pipeTableDraft.ts');
  const payload = {
    created: false,
    issue_count: 1,
    issues: [{
      row: null, field: 'path', code: 'table_encrypted', params: {},
      reason: 'the file is protected (encrypted or DRM); save an unprotected copy',
    }],
  };
  const koHtml = render('ko', presentPipeDraft('pipe_table_import', payload));
  assert.match(koHtml, /보호되어 있습니다/);
  assert.doesNotMatch(koHtml, /The file is protected/);
  assert.doesNotMatch(koHtml, /save an unprotected copy/);
  const enHtml = render('en', presentPipeDraft('pipe_table_import', payload));
  assert.match(enHtml, /The file is protected \(encrypted or DRM\)\. Save an unprotected copy\./);
});

test('FER4-L2: every reason key maps back to a registry code', () => {
  const keys = Object.keys(ko).filter((key) => key.startsWith('pipeDraft.reason.') && key !== 'pipeDraft.reason.spec');
  const back = keys.map((key) => key.slice('pipeDraft.reason.'.length));
  assert.deepEqual([...back].sort(), [...codes].sort());
  assert.deepEqual(codes, [...new Set(codes)]);
});

test('FER4-L4: no ko reason key breaks after a consonant-ending name', () => {
  for (const key of Object.keys(ko).filter((key) => key.startsWith('pipeDraft.reason.'))) {
    assert.doesNotMatch(ko[key], /\{node\}는/, `${key} avoids the 는 particle after a name`);
    assert.doesNotMatch(ko[key], /\{flowpath\}는/, `${key} avoids the 는 particle after a name`);
  }
});

test('FER4-L5: the formatter stays lean', async () => {
  const draft = await read('../src/pipeTableDraft.ts');
  assert.doesNotMatch(draft, /as I18nKey/, 'no casts on the translate calls');
  assert.doesNotMatch(draft, /export function draftReasonKey/, 'the key lookup stays module-private');
  assert.doesNotMatch(draft, /for \(const \[name, value\] of Object\.entries\(issue\.params\)\)/, 'no copy loop over params');
});

test('FER5: endpoint issues format with their params', async () => {
  const { formatDraftReason } = await import('../src/pipeTableDraft.ts');
  const t = (key, vars) => translate('ko', key, vars);
  const mismatch = formatDraftReason(
    {
      row: 2, field: 'length_m', reason: 'the stated length disagrees', code: 'endpoints_length_mismatch',
      params: { stated_m: 12.5, actual_m: 10 },
    },
    t,
  );
  assert.match(mismatch, /12\.5/);
  assert.match(mismatch, /10/);
  assert.match(mismatch, /[가-힣]/);
  assert.doesNotMatch(
    formatDraftReason(
      { row: 1, field: 'x_m', reason: 'give x_m, y_m and z_m together as numbers', code: 'endpoints_end_missing', params: {} },
      (key, vars) => translate('en', key, vars),
    ),
    /[가-힣]/,
  );
});

test('FER6: the columns_given code has ko/en keys', () => {
  for (const key of ['pipeDraft.reason.endpoints_columns_given']) {
    assert.ok(key in ko, `ko has ${key}`);
    assert.ok(key in en, `en has ${key}`);
    assert.match(ko[key], /{column}/);
    assert.match(en[key], /{column}/);
  }
});

test('FER6: mismatch reasons say the larger of 1% and 0.01 m', async () => {
  const { formatDraftReason } = await import('../src/pipeTableDraft.ts');
  const issue = (code, field) => ({
    row: 2, field, reason: 'the stated length disagrees', code,
    params: { stated_m: 12.5, actual_m: 10 },
  });
  for (const code of ['endpoints_length_mismatch', 'endpoints_rise_mismatch']) {
    const koText = formatDraftReason(issue(code, code.includes('rise') ? 'elevation_m' : 'length_m'), (key, vars) => translate('ko', key, vars));
    assert.match(koText, /1%와 0\.01m 중 큰 값/);
    const enText = formatDraftReason(issue(code, 'length_m'), (key, vars) => translate('en', key, vars));
    assert.match(enText, /larger of 1% and 0\.01 m/);
  }
});

test('FER7: the cycle sentence renders in Korean from the real backend params', async () => {
  const { formatDraftReason } = await import('../src/pipeTableDraft.ts');
  const koText = formatDraftReason(
    {
      row: 3, field: 'x_m', reason: 'this pipe closes a loop; loops are refused',
      code: 'endpoints_cycle', params: {},
    },
    (key, vars) => translate('ko', key, vars),
  );
  assert.match(koText, /고리를 닫아요/);
  assert.doesNotMatch(koText, /loops are refused/);
  const enText = formatDraftReason(
    {
      row: 3, field: 'x_m', reason: 'this pipe closes a loop; loops are refused',
      code: 'endpoints_cycle', params: {},
    },
    (key, vars) => translate('en', key, vars),
  );
  assert.match(enText, /closes a loop/);
  assert.doesNotMatch(enText, /\{at\}/);
});

test('FER7: the columns_given sentence names the field and suggests column_map', async () => {
  const { formatDraftReason } = await import('../src/pipeTableDraft.ts');
  const issue = {
    row: null, field: 'pressure', reason: 'the diameter_m column is not used', code: 'endpoints_columns_given',
    params: { column: 'diameter_m' },
  };
  const koText = formatDraftReason(issue, (key, vars) => translate('ko', key, vars));
  assert.match(koText, /diameter_m/);
  assert.match(koText, /column_map/);
  const enText = formatDraftReason(issue, (key, vars) => translate('en', key, vars));
  assert.match(enText, /diameter_m/);
  assert.match(enText, /remove the column/);
  assert.match(enText, /column_map/);
});

test('FER6: the at word reads translated in ko and falls back when missing', async () => {
  const { formatDraftReason, presentPipeDraft } = await import('../src/pipeTableDraft.ts');
  const t = (key, vars) => translate('ko', key, vars);
  const chain = (params) => ({
    row: 3, field: 'x_m', reason: 'a chain node needs one pipe in and one out; it has 0 in and 2 out',
    code: 'endpoints_chain_orientation', params,
  });
  assert.match(formatDraftReason(chain({ incoming: 0, outgoing: 2, at: 'start' }), t), /시작점/);
  const enChain = formatDraftReason(chain({ incoming: 0, outgoing: 2, at: 'end' }), (key, vars) => translate('en', key, vars));
  assert.match(enChain, /at its end/);
  assert.match(
    formatDraftReason(chain({ incoming: 0, outgoing: 2, at: 'middle' }), t),
    /middle/,
    'an unknown at word stays raw',
  );
  const view = presentPipeDraft('pipe_table_import', {
    created: false,
    issue_count: 1,
    issues: [{
      row: 3, field: 'x_m', reason: 'a chain node needs one pipe in and one out; it has 0 in and 2 out',
      code: 'endpoints_chain_orientation', params: { incoming: 0, outgoing: 2 },
    }],
  });
  assert.equal(
    formatDraftReason(view.issues[0], t),
    'a chain node needs one pipe in and one out; it has 0 in and 2 out',
  );
});

test('FER5: kind words read translated in ko and raw when unknown', async () => {
  const { formatDraftReason } = await import('../src/pipeTableDraft.ts');
  const issue = (kind) => ({
    row: 9, field: 'SRC', reason: 'a source needs 1 outgoing and 0 incoming flowpaths',
    code: 'boundary_bad_degree', params: { node: 'SRC', kind, incoming: 0, outgoing: 1 },
  });
  const t = (key, vars) => translate('ko', key, vars);
  assert.match(formatDraftReason(issue('source'), t), /SRC 입구이지만/);
  assert.match(formatDraftReason(issue('sink'), t), /SRC 출구이지만/);
  assert.match(formatDraftReason(issue('mystery'), t), /SRC mystery이지만/);
  const en = formatDraftReason(issue('source'), (key, vars) => translate('en', key, vars));
  assert.match(en, /SRC is a source but has/);
});
