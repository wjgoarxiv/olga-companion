// M7: the edit table's approval card says the valve schedule (or time series) goes away.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (p) => readFile(new URL(p, import.meta.url), 'utf8');

test('each reviewed change with a schedule or series shows the removal note', async () => {
  const table = await read('../src/CaseEditTable.tsx');
  const review = table.slice(table.indexOf('case-edit-changes'));
  assert.match(review, /change\.row\.note && <span className="case-edit-review-note" role="note">\{t\(`caseEdit\.reviewNote\.\$\{change\.row\.note\}`, \{ value: change\.after \}\)\}/);
});

test('both removal notes exist in English and Korean with the new value', async () => {
  for (const file of ['../src/i18n/en.ts', '../src/i18n/ko.ts']) {
    const text = await read(file);
    for (const note of ['schedule', 'series']) {
      assert.match(text, new RegExp(`'caseEdit\\.reviewNote\\.${note}': '[^']*\\{value\\}[^']*'`), `${file} ${note}`);
    }
  }
});
