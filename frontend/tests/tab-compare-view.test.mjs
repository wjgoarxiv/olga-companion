import assert from 'node:assert/strict';
import test from 'node:test';
import { tabCompareRenderer } from './helpers/render-tab-compare.mjs';

const render = await tabCompareRenderer();

const result = {
  reference: { path: 'owner.tab', label: 'NEUTRAL-OWNER', phase: 'TWO' },
  candidate: { path: 'engine.tab', label: 'NEUTRAL-ENGINE', phase: 'TWO' },
  grid: { method: 'common_nodes', reference_nodes: 4, candidate_nodes: 4 },
  compared_nodes: 4,
  columns: {
    ROG: {
      nodes: 4, mean_rel_diff: 0.0125, max_rel_diff: 0.05,
      max_location: { pressure_pa: 500000, temperature_c: 0 }, zero_reference_nodes: 0,
    },
    ROHL: {
      nodes: 4, mean_rel_diff: 0, max_rel_diff: 0,
      max_location: { pressure_pa: 500000, temperature_c: 0 }, zero_reference_nodes: 0,
    },
  },
  skipped_columns: [],
  regions: {
    gas_only: { nodes: 4, mean_rel_diff: 0.006 },
    liquid_only: { nodes: 0, mean_rel_diff: 0 },
    two_phase: { nodes: 0, mean_rel_diff: 0 },
  },
  region_basis: 'RS',
  filled: { reference: ['SIGGHL'], candidate: [] },
  heat: {
    pressures_pa: [500000, 2000000],
    temperatures_c: [0, 40],
    columns: { ROG: [[0.05, 0], [0, 0]], ROHL: [[0, 0], [0, 0]] },
  },
  trace: null,
  trace_note: 'File-based comparison carries no per-node engine trace.',
  summary_en: 'Compared 4 of 4 reference and 4 candidate nodes (common_nodes).',
  summary_ko: '기준 4개·후보 4개 노드 중 4개 비교(common_nodes).',
  writes_nothing: true,
};

test('the comparison view renders the bilingual summary and the column table', () => {
  const ko = render('ko', result);
  assert.match(ko, /기준 4개·후보 4개 노드/);
  assert.match(ko, /ROG/);
  assert.match(ko, /0\.05/);
  const en = render('en', result);
  assert.match(en, /Compared 4 of 4 reference/);
  assert.match(en, /ROG/);
});

test('the comparison view shows regions, filled columns and a heat strip per column', () => {
  const html = render('en', result);
  assert.match(html, /Gas-only|Gas only/i);
  assert.match(html, /SIGGHL/);
  assert.match(html, /<dl class="evidence-metrics tabcompare-regions"/);
  assert.match(html, /data-testid="tabcompare-heat-ROG"/);
  assert.match(html, /tabcompare-heat-cell/);
});

test('the comparison view offers the calculation disclosure in both locales', () => {
  assert.match(render('ko', result), /계산 과정 보기/);
  assert.match(render('en', result), /Show calculation/);
});

const zeroReferenceResult = {
  ...result,
  columns: {
    ...result.columns,
    SIGGHL: {
      nodes: 4, relative_nodes: 0, mean_rel_diff: null, max_rel_diff: null, max_location: null,
      zero_reference_nodes: 4, zero_reference_max_abs_diff: 0.0123,
    },
    HG: {
      nodes: 4, relative_nodes: 3, mean_rel_diff: 0.02, max_rel_diff: 0.02,
      max_location: { pressure_pa: 2000000, temperature_c: 40 },
      zero_reference_nodes: 1, zero_reference_max_abs_diff: 5,
    },
  },
  heat: {
    pressures_pa: [500000, 2000000],
    temperatures_c: [0, 40],
    pressure_ranges_pa: [[500000, 1000000], [2000000, 2000000]],
    temperature_ranges_c: [[0, 20], [40, 40]],
    columns: {
      ROG: [[0.05, null], [0, 0]],
      ROHL: [[0, 0], [0, 0]],
      SIGGHL: [[null, null], [null, null]],
      HG: [[null, 0.02], [0.02, 0.02]],
    },
  },
  warnings: [{
    code: 'components_differ',
    message_en: 'The two tables list different components (reference: CO2, N2), so the composition differs.',
    message_ko: '두 표의 성분이 다릅니다. 조성이 달라 같은 유체의 비교가 아닙니다.',
  }],
};

function rowOf(html, name) {
  const match = html.match(new RegExp(`<tr><th scope="row">${name}</th>.*?</tr>`));
  assert.ok(match, `row ${name}`);
  return match[0];
}

test('a column with no relative difference shows a dash and its absolute number separately', () => {
  for (const locale of ['en', 'ko']) {
    const html = render(locale, zeroReferenceResult);
    const row = rowOf(html, 'SIGGHL');
    assert.equal((row.match(/—/g) ?? []).length >= 3, true, 'mean, max and location are dashes');
    assert.doesNotMatch(row, /<td>0<\/td>/, 'a missing relative difference is never drawn as zero');
    assert.match(row, /data-testid="tabcompare-zero-SIGGHL"[^>]*>[^<]*0\.0123/);
    assert.match(rowOf(html, 'HG'), /data-testid="tabcompare-zero-HG"[^>]*>[^<]*5/);
    assert.doesNotMatch(rowOf(html, 'ROG'), /tabcompare-zero/, 'a column without zero nodes has no such cell');
  }
  assert.match(render('en', zeroReferenceResult), /absolute/i);
  assert.match(render('ko', zeroReferenceResult), /절대/);
});

test('an uncompared heat cell is a distinct hatched cell with a localized title', () => {
  const en = render('en', zeroReferenceResult);
  const empty = en.match(/<span[^>]*tabcompare-heat-cell is-empty[^>]*>/g) ?? [];
  assert.ok(empty.length >= 1);
  assert.match(empty[0], /title="[^"]*nothing compared/i);
  const ko = render('ko', zeroReferenceResult);
  assert.match(ko.match(/<span[^>]*tabcompare-heat-cell is-empty[^>]*>/)[0], /title="[^"]*비교한 값 없음/);
  // A real zero difference is a drawn cell, not an empty one.
  const roh = en.match(/data-testid="tabcompare-heat-ROHL".*?<\/section>/s)[0];
  assert.doesNotMatch(roh, /is-empty/);
  // Every cell of an all-empty column is empty.
  const sig = en.match(/data-testid="tabcompare-heat-SIGGHL".*?<\/section>/s)[0];
  assert.equal((sig.match(/is-empty/g) ?? []).length, 4);
});

test('a binned heat cell names its range and says it shows the largest difference', () => {
  const en = render('en', zeroReferenceResult);
  assert.match(en, /500000–1000000/);
  assert.match(en, /largest difference in its range/i);
  assert.match(render('ko', zeroReferenceResult), /가장 큰 차이/);
});

test('a composition warning is shown in the active language', () => {
  const en = render('en', zeroReferenceResult);
  assert.match(en, /class="tabcompare-warning"/);
  assert.match(en, /different components/);
  assert.doesNotMatch(en, /두 표의 성분/);
  const ko = render('ko', zeroReferenceResult);
  assert.match(ko, /두 표의 성분이 다릅니다/);
  assert.doesNotMatch(render('en', result), /tabcompare-warning/);
});

// ---- present-phase headline and phase disagreement (Multiflash comparison findings)

const presentPhaseResult = {
  ...result,
  columns: {
    ROG: {
      nodes: 4, relative_nodes: 4, mean_rel_diff: 1.53, max_rel_diff: 6.11,
      max_location: { pressure_pa: 800000, temperature_c: 10 }, zero_reference_nodes: 0,
      zero_reference_max_abs_diff: 0,
    },
    ROHL: {
      nodes: 4, relative_nodes: 4, mean_rel_diff: 2.1, max_rel_diff: 8,
      max_location: { pressure_pa: 200000, temperature_c: 10 }, zero_reference_nodes: 0,
      zero_reference_max_abs_diff: 0,
    },
    RS: {
      nodes: 4, relative_nodes: 3, mean_rel_diff: 0.4, max_rel_diff: 0.5,
      max_location: { pressure_pa: 200000, temperature_c: 10 }, zero_reference_nodes: 1,
      zero_reference_max_abs_diff: 0.1,
    },
  },
  present_phase: {
    basis: 'RS',
    headline: {
      column: 'ROG', max_rel_diff: 0.02, max_location: { pressure_pa: 200000, temperature_c: 30 },
    },
    columns: {
      ROG: {
        scope: 'gas', nodes: 3, relative_nodes: 3, mean_rel_diff: 0.01, max_rel_diff: 0.02,
        max_location: { pressure_pa: 200000, temperature_c: 30 },
      },
      ROHL: {
        scope: 'liquid', nodes: 2, relative_nodes: 2, mean_rel_diff: 0.04, max_rel_diff: 0.05,
        max_location: { pressure_pa: 800000, temperature_c: 10 },
      },
      RS: {
        scope: 'all', nodes: 4, relative_nodes: 3, mean_rel_diff: 0.4, max_rel_diff: 0.5,
        max_location: { pressure_pa: 200000, temperature_c: 10 },
      },
    },
  },
  phase_disagreement: {
    basis: 'RS', count: 2, truncated: false,
    nodes: [
      { pressure_pa: 200000, temperature_c: 10, reference: 'gas_only', candidate: 'liquid_only' },
      { pressure_pa: 800000, temperature_c: 30, reference: 'gas_only', candidate: 'two_phase' },
    ],
  },
};

test('the present-phase figures are the headline and the all-node figures are labelled as filled', () => {
  for (const [locale, filledHeader, scopeGas] of [
    ['en', /Including filled values/, /Gas/],
    ['ko', /채움값 포함/, /가스/],
  ]) {
    const html = render(locale, presentPhaseResult);
    const rog = rowOf(html, 'ROG');
    assert.match(rog, /0\.01/, 'present-phase mean');
    assert.match(rog, /0\.02/, 'present-phase max');
    assert.match(rog, /data-testid="tabcompare-filled-ROG"[^>]*>[^<]*6\.11/, 'all-node max is the secondary figure');
    assert.match(rog, scopeGas);
    assert.match(rog, /3/, 'present node count');
    assert.match(html, filledHeader);
    const headline = html.match(/data-testid="tabcompare-headline"[^>]*>(.*?)<\/p>/s);
    assert.ok(headline, 'headline line');
    assert.match(headline[1], /ROG/);
    assert.match(headline[1], /0\.02/);
    assert.doesNotMatch(headline[1], /6\.11/, 'the headline never carries the filled-value peak');
    const secondary = html.match(/data-testid="tabcompare-headline-all"[^>]*>(.*?)<\/p>/s);
    assert.ok(secondary, 'secondary line');
    assert.match(secondary[1], /ROHL/);
    assert.match(secondary[1], /\b8\b/);
  }
  assert.match(render('en', presentPhaseResult), /including filled values/i);
});

test('a result without the present-phase block keeps the all-node figures as the headline', () => {
  const html = render('en', zeroReferenceResult);
  assert.doesNotMatch(html, /tabcompare-headline/);
  assert.doesNotMatch(html, /tabcompare-filled-ROG/);
  assert.match(rowOf(html, 'ROG'), /0\.0125/);
});

test('nodes where the phase label differs are counted and located in both locales', () => {
  const en = render('en', presentPhaseResult);
  const block = en.match(/data-testid="tabcompare-phase-disagree".*?<\/section>/s);
  assert.ok(block, 'disagreement block');
  assert.match(block[0], /2 nodes/);
  assert.match(block[0], /200000/);
  assert.match(block[0], /Gas-only/);
  assert.match(block[0], /Liquid-only/);
  assert.match(block[0], /Two-phase/);
  const ko = render('ko', presentPhaseResult);
  const koBlock = ko.match(/data-testid="tabcompare-phase-disagree".*?<\/section>/s);
  assert.ok(koBlock);
  assert.match(koBlock[0], /2개 노드/);
  assert.match(koBlock[0], /상 구분/);
  assert.match(koBlock[0], /가스 단상/);
});

test('no phase disagreement draws no disagreement block', () => {
  const none = {
    ...presentPhaseResult,
    phase_disagreement: { basis: 'RS', count: 0, truncated: false, nodes: [] },
  };
  assert.doesNotMatch(render('en', none), /tabcompare-phase-disagree/);
  assert.doesNotMatch(render('en', result), /tabcompare-phase-disagree/);
});

test('a truncated disagreement list says how many are not listed', () => {
  const truncated = {
    ...presentPhaseResult,
    phase_disagreement: { ...presentPhaseResult.phase_disagreement, count: 60, truncated: true },
  };
  assert.match(render('en', truncated), /58 more/);
  assert.match(render('ko', truncated), /58개 더/);
});
