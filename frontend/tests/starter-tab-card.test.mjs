import assert from 'node:assert/strict';
import test from 'node:test';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';

const render = await approvalCardRenderer();

const row = (key, value, unit) => (unit === undefined ? { key, value } : { key, value, unit });

const KIND = {
  en: 'Generic air-water table (CPA, 0–80 °C, 0.5–20 bar). Not made for your case; check that it covers your conditions.',
  ko: '범용 공기-물 표 (CPA, 0–80 °C, 0.5–20 bar). 내 사례에 맞춘 표가 아니므로 운전 조건이 범위 안인지 확인하세요.',
};

const request = (locale) => ({
  name: 'fluids_starter_tab',
  call_id: 'call_starter',
  pending_id: 'pending_starter',
  args: { tab_rel: 'fluids/air_water.tab' },
  display: {
    fields: [
      row('file', 'fluids/air_water.tab'),
      row('label', 'AIR_WATER'),
      row('model', 'CPA'),
      row('temperature_range', '0 – 80', 'degC'),
      row('pressure_range', '0.5 – 20', 'bar'),
      row('table_kind', KIND[locale]),
    ],
  },
});

test('the starter table card says it is a generic air-water table, in English', () => {
  const html = render('en', request('en'));
  for (const text of ['fluids/air_water.tab', 'AIR_WATER', 'CPA', '0 – 80 degC', '0.5 – 20 bar', KIND.en]) {
    assert.ok(html.includes(text), `en card shows ${text}`);
  }
  assert.match(html, /Approval needed — Add the generic air-water table \(\.tab\)/);
  assert.match(html, /Approve and write the file/);
  assert.doesNotMatch(html, /fluids_starter_tab/i, 'the tool name is not shown');
  assert.doesNotMatch(html, /sandbox/i, 'a file write is not a sandbox run');
});

test('the starter table card says it is a generic air-water table, in Korean', () => {
  const html = render('ko', request('ko'));
  for (const text of ['fluids/air_water.tab', 'AIR_WATER', 'CPA', '0 – 80 degC', '0.5 – 20 bar', KIND.ko]) {
    assert.ok(html.includes(text), `ko card shows ${text}`);
  }
  assert.match(html, /승인 필요 — 범용 공기-물 표\(\.tab\) 추가/);
  assert.doesNotMatch(html, /fluids_starter_tab/i);
});
