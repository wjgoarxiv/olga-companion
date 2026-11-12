import assert from 'node:assert/strict';
import test from 'node:test';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';

const render = await approvalCardRenderer();

const row = (key, value, unit) => (unit === undefined ? { key, value } : { key, value, unit });

const fluids = {
  name: 'fluids_draft_mfl',
  call_id: 'call_fluids',
  pending_id: 'pending_fluids',
  args: { fluid_label: 'SYN1', model: 'SRK' },
  display: {
    fields: [
      row('file', 'fluids/synthetic.mfl'),
      row('table_file', 'fluids/synthetic.tab'),
      row('label', 'SYN1'),
      row('component', 'METHANE 0.85'),
      row('component', 'ETHANE 0.15'),
      row('model', 'SRK'),
      row('temperature_range', '-10 – 120', 'degC'),
      row('temperature_points', '3'),
      row('pressure_range', '1 – 100', 'bar'),
      row('pressure_points', '4'),
    ],
  },
};

const otherKinds = [
  ['multiflash_open', [row('program', 'Multiflash'), row('file', 'synthetic.mfl')]],
  ['genkey_save', [row('file', 'cases/new.genkey'), row('topology', 'single_pipe'), row('end_time', '7200', 's'), row('pvt_file', './fluid.tab')]],
  ['run_cancel', [row('run_id', 'run_abc123')]],
  ['sweep_cancel', [row('sweep_id', 'sweep_abc123')]],
  ['sweep_execute', [row('sweep_id', 'sweep_abc123'), row('case', 'base.genkey'), row('case_count', '2'), row('timeout', '900', 's'), row('plan_id', 'plan_exact')]],
];

const request = (name, fields) => ({
  name,
  call_id: `call_${name}`,
  pending_id: `pending_${name}`,
  args: {},
  display: { fields },
});

test('the fluids draft card shows its content in English', () => {
  const html = render('en', fluids);
  for (const text of [
    'fluids/synthetic.mfl', 'fluids/synthetic.tab', 'SYN1', 'METHANE 0.85', 'ETHANE 0.15', 'SRK',
    '-10 – 120 degC', '1 – 100 bar',
  ]) {
    assert.ok(html.includes(text), `en card shows ${text}`);
  }
  for (const label of ['File', 'Fluid label', 'Model (EOS)', 'Temperature range', 'Pressure range', 'Temperature points', 'Pressure points']) {
    assert.ok(html.includes(`<dt>${label}</dt>`), `en label ${label}`);
  }
  assert.doesNotMatch(html, /fluids_draft_mfl/i, 'the tool name is not the heading');
  assert.match(html, /Approval needed — Write the Multiflash draft file/);
});

test('the fluids draft card shows its content in Korean', () => {
  const html = render('ko', fluids);
  for (const text of ['fluids/synthetic.mfl', 'SYN1', 'METHANE 0.85', 'SRK', '-10 – 120 degC', '1 – 100 bar']) {
    assert.ok(html.includes(text), `ko card shows ${text}`);
  }
  for (const label of ['파일', '유체 이름', '모델 (EOS)', '온도 범위', '압력 범위', '온도 점 수', '압력 점 수']) {
    assert.ok(html.includes(`<dt>${label}</dt>`), `ko label ${label}`);
  }
  assert.doesNotMatch(html, /fluids_draft_mfl/i);
  assert.match(html, /승인 필요 — Multiflash 초안 파일 쓰기/);
});

test('a file write is not described as a sandbox run', () => {
  assert.doesNotMatch(render('en', fluids), /sandbox/i);
  assert.doesNotMatch(render('ko', fluids), /샌드박스/);
});

for (const locale of ['en', 'ko']) {
  for (const [name, fields] of otherKinds) {
    test(`${name} card has a readable heading and its fields in ${locale}`, () => {
      const html = render(locale, request(name, fields));
      assert.doesNotMatch(html, new RegExp(`approval-head">[^<]*${name}`, 'i'), 'the heading is words, not the tool name');
      for (const { value } of fields) assert.ok(html.includes(value), `${locale} ${name} shows ${value}`);
      assert.doesNotMatch(html, /<dl><\/dl>/, 'the field list is never empty');
    });
  }
}

test('ids and plan hashes sit in technical rows, not in the heading', () => {
  const html = render('en', request('sweep_execute', otherKinds.find(([name]) => name === 'sweep_execute')[1]));
  assert.match(html, /<dd class="evidence-value-technical">plan_exact<\/dd>/);
  assert.doesNotMatch(html, /approval-head">[^<]*plan_exact/);
});

test('sweep fields are not repeated by the legacy sweep rows', () => {
  const html = render('en', {
    ...request('sweep_execute', otherKinds.find(([name]) => name === 'sweep_execute')[1]),
    args: { sweep_id: 'sweep_abc123', plan_id: 'plan_exact' },
  });
  assert.equal(html.split('sweep_abc123').length - 1, 1, 'the sweep id appears once');
  assert.equal(html.split('plan_exact').length - 1, 1, 'the plan id appears once');
});

test('the run card keeps its case file and timeout rows', () => {
  const html = render('en', {
    name: 'run_execute',
    call_id: 'call_run',
    pending_id: 'pending_run',
    args: {},
    display: {
      case: 'case.genkey', selection_id: 'selection_exact', runtime_id: 'olga-2022.1', executable: 'OLGA.exe',
      output_target: 'managed-run-sandbox', source_sha256: 'a'.repeat(64), timeout_s: 120,
    },
  });
  assert.ok(html.includes('case.genkey'));
  assert.ok(html.includes('120 seconds'));
  assert.doesNotMatch(html, /approval-head">[^<]*run_execute/i);
});

test('a card without server fields still renders and keeps its buttons', () => {
  const html = render('en', { name: 'fluids_draft_mfl', call_id: 'c', pending_id: 'p', args: {}, display: {} });
  assert.match(html, /class="ui-button ui-button-primary approve"/);
  assert.match(html, /class="ui-button ui-button-secondary reject"/);
});

test('malformed field rows are skipped, never rendered as text', () => {
  const html = render('en', request('multiflash_open', [row('program', 'Multiflash'), { key: 7, value: 'bad' }, null, { key: 'file' }, { key: 'file', value: 5 }]));
  assert.ok(html.includes('Multiflash'));
  assert.doesNotMatch(html, />bad</);
});

test('the approve button names what approving does, per kind', () => {
  const expected = {
    fluids_draft_mfl: ['Approve and write the file', '승인하고 파일 쓰기'],
    genkey_save: ['Approve and write the file', '승인하고 파일 쓰기'],
    multiflash_open: ['Approve and open', '승인하고 열기'],
    run_cancel: ['Approve and cancel', '승인하고 취소'],
    sweep_cancel: ['Approve and cancel', '승인하고 취소'],
    run_execute: ['Approve and run', '승인하고 실행'],
    sweep_execute: ['Approve and run', '승인하고 실행'],
  };
  for (const [name, [en, ko]] of Object.entries(expected)) {
    const req = { name, call_id: 'c', pending_id: 'p', args: {}, display: {} };
    assert.ok(render('en', req).includes(`>${en}<`), `${name} en button`);
    assert.ok(render('ko', req).includes(`>${ko}<`), `${name} ko button`);
  }
});
