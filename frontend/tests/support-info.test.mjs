// N7: the version table shows each OLGA install, which one is in use and whether the app can start it.
import assert from 'node:assert/strict';
import test from 'node:test';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const rows = [
  { version: '2025.1.0', kind: 'engine', source: 'standard_glob', file: 'OLGA-2025.1.0.exe', runnable: true, selected: true },
  { version: '2022.1.0', kind: 'opi', source: 'standard_glob', file: 'opi.exe', runnable: false, selected: false },
];

test('each install is a row with its program file, in Korean', () => {
  const html = r.renderVersionMatrix('ko', rows);
  assert.match(html, /<caption>찾은 OLGA 설치<\/caption>/);
  assert.match(html, /<tr aria-current="true"><td>2025\.1\.0 · 사용 중<\/td><td><code>OLGA-2025\.1\.0\.exe<\/code><\/td><td>가능<\/td><\/tr>/);
  assert.match(html, /<td>2022\.1\.0<\/td><td><code>opi\.exe<\/code><\/td><td>불가<\/td>/);
});

test('English labels, and a plain line when nothing was found', () => {
  assert.match(r.renderVersionMatrix('en', rows), /<th scope="col">App can start it<\/th>/);
  assert.match(r.renderVersionMatrix('en', []), /No OLGA install found\./);
});

test('two installs with the same version and program name are two rows (review)', () => {
  const same = { version: '2022.1.0', kind: 'engine', source: 'standard_glob', file: 'OLGA-2022.1.0.exe', runnable: true, selected: false };
  const html = r.renderVersionMatrix('en', [same, { ...same, source: 'env' }]);
  assert.equal(html.match(/<code>OLGA-2022\.1\.0\.exe<\/code>/g).length, 2);
});

test('support info is a read-only text box to copy with Ctrl+C, with no copy button (N7 PVT: no clipboard prompt)', () => {
  const bundle = { schema: 1, app_version: '0.1.19', olga: rows };
  const html = r.renderSupportText('ko', bundle);
  assert.match(html, /<summary>지원 정보 보기<\/summary>/);
  assert.match(html, /<textarea[^>]*readonly=""[^>]*>/i);
  assert.ok(html.includes('&quot;app_version&quot;: &quot;0.1.19&quot;'), 'the text box holds the support info');
  assert.match(html, /Ctrl\+C/);
  assert.doesNotMatch(html, /<button/);
  assert.match(r.renderSupportText('en', bundle), /<summary>Show support info<\/summary>/);
});
