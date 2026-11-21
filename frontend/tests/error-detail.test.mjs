import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

/* 0.1.22 row 5: a coded server refusal reads with a headline in the app language and keeps the
 * server's own words below it, untranslated and selectable. An unknown code says so; nothing is blank. */

const RAW = "Could not read a series for 'HOL' from case.tpl.";

test('a known code shows its Korean headline and the raw English line below', async () => {
  const { renderErrorDetail } = await reviewNotesRenderer();
  const html = renderErrorDetail('ko', 'series_unreadable', RAW);
  assert.match(html, /결과 파일에서 이 변수를 읽지 못했습니다\./);
  assert.match(html, /<pre class="error-detail-raw" lang="en">Could not read a series for &#x27;HOL&#x27; from case\.tpl\.<\/pre>/);
});

test('a known code reads in English in the English app', async () => {
  const { renderErrorDetail } = await reviewNotesRenderer();
  assert.match(renderErrorDetail('en', 'profile_unreadable', RAW), /This profile could not be read from the result file\./);
});

test('an unknown code shows the not-translated label with the raw text', async () => {
  const { renderErrorDetail } = await reviewNotesRenderer();
  const ko = renderErrorDetail('ko', 'brand_new_code', RAW);
  assert.match(ko, /번역되지 않은 메시지/);
  assert.match(ko, /from case\.tpl/);
  assert.match(renderErrorDetail('en', 'brand_new_code', RAW), /Message not yet translated/);
});

test('an empty raw text is never shown blank', async () => {
  const { renderErrorDetail } = await reviewNotesRenderer();
  assert.match(renderErrorDetail('ko', 'series_unreadable', '   '), /앱이 더 자세한 내용을 주지 않았습니다\./);
});

test('every server code the result routes send has a headline in both languages', async () => {
  const source = await readFile(new URL('../../src/olga_companion/results.py', import.meta.url), 'utf8');
  const codes = [...source.matchAll(/CodedInputError\(\s*"([a-z_]+)"/g)].map((match) => match[1]);
  assert.ok(codes.length >= 8, `found ${codes.length} codes`);
  const [en, ko] = await Promise.all(['en', 'ko'].map((name) => readFile(new URL(`../src/i18n/${name}.ts`, import.meta.url), 'utf8')));
  for (const code of new Set(codes)) {
    assert.match(en, new RegExp(`'serverError\\.${code}':`), `en headline for ${code}`);
    assert.match(ko, new RegExp(`'serverError\\.${code}':`), `ko headline for ${code}`);
  }
});

test('review R10: a coded profile read error shows its headline and keeps the raw text', async () => {
  const { renderProfileError } = await reviewNotesRenderer();
  const html = renderProfileError('ko', 'Profile file is unreadable: case.ppl', 'profile_unreadable');
  assert.doesNotMatch(html, /serverError\./);
  assert.match(html, /Profile file is unreadable: case\.ppl/);
  assert.match(html, /lang="en"/);
  const views = await readFile(new URL('../src/ResultsView.tsx', import.meta.url), 'utf8');
  assert.match(views, /setProfileErrorCode\(errorCodeOf\(cause\)\)/);
});

test('the plot tab and the run failure panel use the coded error view', async () => {
  const plot = await readFile(new URL('../src/ResultPlotTab.tsx', import.meta.url), 'utf8');
  assert.match(plot, /<ErrorDetail code=\{overlay\.errorCode\} text=\{error\} \/>/);
  const panel = await readFile(new URL('../src/RunFailurePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /!failureText && <p className="run-failure-untranslated">/);
  const response = await readFile(new URL('../src/sessionResponse.ts', import.meta.url), 'utf8');
  assert.match(response, /throw new CodedApiError\(detail\.code\.slice\(0, 64\), detail\.message\)/);
});
