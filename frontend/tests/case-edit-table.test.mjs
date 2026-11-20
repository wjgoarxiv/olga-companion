// The hand-edit table is a real table a keyboard and a screen reader can use, and saving needs the Approve click.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/CaseEditTable.tsx', import.meta.url), 'utf8');
const api = readFileSync(new URL('../src/caseEditApi.ts', import.meta.url), 'utf8');
const view = readFileSync(new URL('../src/WorkspaceView.tsx', import.meta.url), 'utf8');
const stepbar = readFileSync(new URL('../src/shell/StepBar.tsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/styles/case-edit.css', import.meta.url), 'utf8');

test('the table has a caption, column and row headers, and labelled cells', () => {
  assert.match(source, /<caption>/);
  assert.match(source, /<th scope="col">/);
  assert.match(source, /<th scope="row">/);
  assert.match(source, /aria-label=\{`\$\{row\.target\}/);
  assert.match(source, /aria-invalid=/);
});

test('Esc puts a cell back and Enter reviews', () => {
  assert.match(source, /event\.key === 'Escape'[\s\S]*formatDisplay\(row\)/);
  assert.match(source, /event\.key === 'Enter'[\s\S]*review\(\)/);
});

test('saving is only reachable from the Approve button', () => {
  const calls = source.match(/publishCaseEdit\(/g) ?? [];
  assert.equal(calls.length, 1);
  assert.match(source, /onClick=\{\(\) => \{ void approve\(\); \}\}/);
  assert.match(api, /approved: true/);
});

test('the Workspace view opens the table and the step bar Edit action asks for it', () => {
  assert.match(view, /<CaseEditTable/);
  assert.match(view, /t\('caseEdit\.open'\)/);
  assert.match(stepbar, /requestCaseEdit\(\)/);
});

test('the table styles stay square and use tokens', () => {
  assert.doesNotMatch(css, /border-radius:\s*\d/);
  assert.doesNotMatch(css, /font-size:\s*\d/);
  assert.doesNotMatch(css, /#[0-9a-f]{3,6}\b/i);
});
