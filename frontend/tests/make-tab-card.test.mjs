import assert from 'node:assert/strict';
import test from 'node:test';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';

const render = await approvalCardRenderer();

const row = (key, value, unit) => (unit === undefined ? { key, value } : { key, value, unit });

const KIND = {
  en: "Computed by Multiflash from the .mfl's own table command",
  ko: 'Multiflash가 .mfl의 표 명령대로 계산한 표',
};

const request = (locale) => ({
  name: 'fluids_make_tab',
  call_id: 'call_make',
  pending_id: 'pending_make',
  args: { source_rel: 'fluids/gas.mfl', tab_rel: 'fluids/gas.tab' },
  display: {
    fields: [
      row('file', 'fluids/gas.tab'),
      row('mfl_file', 'fluids/gas.mfl'),
      row('label', 'GAS'),
      row('pressure_range', '1 – 100', 'bar'),
      row('temperature_range', '-10 – 60', 'degC'),
      row('table_kind', KIND[locale].replace("'", '’')),
    ],
  },
});

for (const [locale, title] of [
  ['en', /Approval needed — Make the \.tab with Multiflash/],
  ['ko', /승인 필요 — Multiflash로 표\(\.tab\) 만들기/],
]) {
  test(`the make-table card names the .mfl, the new file and the range (${locale})`, () => {
    const html = render(locale, request(locale));
    for (const text of ['fluids/gas.tab', 'fluids/gas.mfl', 'GAS', '1 – 100 bar', '-10 – 60 degC', KIND[locale].replace("'", '’')]) {
      assert.ok(html.includes(text), `${locale} card shows ${text}`);
    }
    assert.match(html, title);
    assert.ok(html.includes(locale === 'en' ? 'Multiflash draft (.mfl)' : 'Multiflash 초안 (.mfl)'), 'the source is called a Multiflash file');
    assert.doesNotMatch(html, /fluids_make_tab/i, 'the tool name is not shown');
    assert.doesNotMatch(html, /sandbox/i, 'a file write is not a sandbox run');
    if (locale === 'en') assert.match(html, /Approve and write the file/);
  });
}
