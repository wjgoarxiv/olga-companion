import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { glossaryTermFor } from '../src/caseEditGlossary.mjs';

/* 0.1.22 row 7: each edit-table row shows the OLGA keyword it changes as a caption. The caption opens
 * the glossary entry for that key on focus or hover; a key the glossary does not explain for this
 * keyword shows the caption alone. */

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('a key is looked up by its own name', () => {
  assert.equal(glossaryTermFor('INTEGRATION.ENDTIME'), 'ENDTIME');
  assert.equal(glossaryTermFor('PARAMETERS.SETPOINT'), 'SETPOINT');
  assert.equal(glossaryTermFor('TREND.DTPLOT'), 'DTPLOT');
});

test('a key whose glossary entry belongs to another keyword is not looked up', () => {
  // The DTPLOT entry describes TREND output; it would be wrong under PROFILE.
  assert.equal(glossaryTermFor('PROFILE.DTPLOT'), null);
});

test('a row without a keyword has no caption term', () => {
  assert.equal(glossaryTermFor(undefined), null);
  assert.equal(glossaryTermFor(''), null);
  assert.equal(glossaryTermFor('NODOT'), null);
});

test('the edit table shows the keyword caption under the field name, through the glossary trigger', async () => {
  const table = await read('../src/CaseEditTable.tsx');
  assert.match(table, /<KeywordCaption keyword=\{row\.keyword\} \/>/);
  const caption = await read('../src/KeywordCaption.tsx');
  // Review R12: the accessible name starts with the visible caption, and the meaning opens in the
  // row instead of floating out of the table's scroll box.
  assert.match(caption, /<GlossaryTerm term=\{term\} label=\{keyword\}>\{keyword\}<\/GlossaryTerm>/);
  const term = await read('../src/GlossaryTerm.tsx');
  assert.match(term, /aria-label=\{`\$\{label \?\? term\}: \$\{meaning\}`\}/);
  const css = await read('../src/styles/case-edit.css');
  assert.match(css, /\.case-edit-keyword \.glossary-pop \{[^}]*position: static;/);
  // PVT D2: the term, meaning and source keep their own lines in the row.
  assert.doesNotMatch(css, /\.case-edit-keyword \.glossary-pop \{[^}]*display: (block|inline)/);
  assert.match(caption, /if \(!keyword\) return null;/);
});

test('the glossary trigger opens on focus and on Enter, and is reachable by Tab', async () => {
  const term = await read('../src/GlossaryTerm.tsx');
  assert.match(term, /tabIndex=\{0\}/);
  assert.match(term, /onFocus=\{\(\) => setOpen\(true\)\}/);
  assert.match(term, /event\.key === 'Enter'/);
  assert.match(term, /if \(entry === null\) return <>\{children\}<\/>;/, 'no entry: the caption alone');
});
