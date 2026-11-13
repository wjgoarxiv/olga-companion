import assert from 'node:assert/strict';
import test from 'node:test';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';

const render = await approvalCardRenderer();

const row = (key, value, unit) => (unit === undefined ? { key, value } : { key, value, unit });

const NOTE = {
  en: 'Independent table, not Multiflash-identical',
  ko: '독립 계산 표 (Multiflash와 같지 않음)',
};

const fields = (locale) => [
  row('file', 'fluids/syn_co2.tab'),
  row('label', 'SYN_CO2'),
  row('component', 'CO2 0.95'),
  row('component', 'N2 0.03'),
  row('component', 'CH4 0.02'),
  row('model', 'PR'),
  row('temperature_range', '-10 – 20', 'degC'),
  row('temperature_points', '4'),
  row('pressure_range', '10 – 30', 'bar'),
  row('pressure_points', '3'),
  row('table_kind', NOTE[locale]),
];

const request = (locale) => ({
  name: 'fluids_generate_tab',
  call_id: 'call_generate',
  pending_id: 'pending_generate',
  args: { fluid_label: 'SYN_CO2' },
  display: { fields: fields(locale) },
});

test('the table generator card shows what will be computed and written, in English', () => {
  const html = render('en', request('en'));
  for (const text of ['fluids/syn_co2.tab', 'SYN_CO2', 'CO2 0.95', 'N2 0.03', 'CH4 0.02', 'PR', '-10 – 20 degC', '10 – 30 bar', NOTE.en]) {
    assert.ok(html.includes(text), `en card shows ${text}`);
  }
  for (const label of ['File', 'Fluid label', 'Model (EOS)', 'Temperature range', 'Pressure range', 'Table type']) {
    assert.ok(html.includes(`<dt>${label}</dt>`), `en label ${label}`);
  }
  assert.match(html, /Approval needed — Generate the fluid table \(\.tab\)/);
  assert.match(html, /Approve and write the file/);
  assert.doesNotMatch(html, /fluids_generate_tab/i, 'the tool name is not shown');
  assert.doesNotMatch(html, /sandbox/i, 'a file write is not a sandbox run');
});

test('the table generator card shows what will be computed and written, in Korean', () => {
  const html = render('ko', request('ko'));
  for (const text of ['fluids/syn_co2.tab', 'SYN_CO2', 'CO2 0.95', 'PR', '-10 – 20 degC', '10 – 30 bar', NOTE.ko]) {
    assert.ok(html.includes(text), `ko card shows ${text}`);
  }
  for (const label of ['파일', '유체 이름', '모델 (EOS)', '온도 범위', '압력 범위', '표 종류']) {
    assert.ok(html.includes(`<dt>${label}</dt>`), `ko label ${label}`);
  }
  assert.match(html, /승인 필요 — 유체 표\(\.tab\) 생성/);
  assert.doesNotMatch(html, /fluids_generate_tab/i);
});

for (const locale of ['en', 'ko']) {
  test(`a plan step for the table generator carries the same rows in ${locale}`, () => {
    const html = render(locale, {
      name: 'action_plan',
      call_id: 'call_plan',
      pending_id: 'pending_plan',
      args: { steps: [{ kind: 'fluids_generate_tab', args: {} }] },
      display: {
        plan: {
          steps: [
            { index: 1, kind: 'fluids_generate_tab', fields: fields(locale) },
            { index: 2, kind: 'case_publish', fields: [row('file', 'cases/new.genkey')] },
          ],
        },
      },
      expires_at: Math.floor(Date.now() / 1000) + 1500,
    });
    for (const text of ['fluids/syn_co2.tab', 'SYN_CO2', 'CO2 0.95', NOTE[locale], '-10 – 20 degC']) {
      assert.ok(html.includes(text), `${locale} plan row shows ${text}`);
    }
    assert.ok(html.includes(locale === 'en' ? 'Generate the fluid table (.tab)' : '유체 표(.tab) 생성'));
    assert.ok(html.includes(locale === 'en' ? 'Table type' : '표 종류'));
    assert.doesNotMatch(html, /fluids_generate_tab/i);
  });
}
