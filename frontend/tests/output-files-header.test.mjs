// 0.1.20 row 7 (D6): the Output files "Open" header sits over its buttons, with no separator tick.
import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const outputs = [{ name: 'case.tpl', suffix: '.tpl', size: 2048, sha256: 'a'.repeat(64), result_id: 'res-1' }];

test('the Open header is right-aligned and has no separator tick', () => {
  for (const locale of ['en', 'ko']) {
    const html = r.renderFailedRun(locale, null, null, {}, outputs);
    const headers = [...html.matchAll(/<th scope="col"([^>]*)>(.*?)<\/th>/g)];
    assert.equal(headers.length, 2, locale);
    const [, attrs, inner] = headers[1];
    assert.match(attrs, /class="[^"]*ui-end/, `${locale} Open header is right-aligned`);
    assert.doesNotMatch(inner, /th-sep/, `${locale} no tick before the Open header`);
    const cells = [...html.matchAll(/<td([^>]*)>/g)];
    assert.match(cells[1][1], /ui-end/, `${locale} the Open cell lines up with its header`);
  }
});
