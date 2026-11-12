import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* W2-L3a (M11): preview receipt in view. After a preview lands, the
   receipt card scrolls into view (block:'nearest' inside the run-body
   scroller); a collapse request for the bottom Problems panel fires ONLY
   when preview.validation.valid && zero case-problem error rows. The shell
   listener that consumes the request is a later wave; this file pins the
   scroll, the guard, and the request contract (name + guarded dispatch). */

test('receipt card scrolls into view when a preview lands', async () => {
  const panel = await read('../src/RunSingleCasePanel.tsx');
  assert.match(panel, /run-preview-card/, 'preview card keeps its hook class');
  assert.match(panel, /scrollIntoView\(\{\s*[^}]*block:\s*['"]nearest['"]/, 'scroll uses block:nearest');
});

test('collapse request fires only for valid previews with zero error rows', async () => {
  const panel = await read('../src/RunSingleCasePanel.tsx');
  assert.match(panel, /validation\.valid/, 'guard reads preview.validation.valid');
  assert.match(panel, /getCaseProblemsSnapshot|severity === 'error'|severity==="error"/, 'guard counts case-problem error rows');
  assert.match(panel, /olga:collapse-problems-panel|COLLAPSE_PROBLEMS/, 'guarded collapse request has a stable contract name');
  assert.doesNotMatch(panel, /setPanelOpen|onToggle\(false\)/, 'no direct panel state writes from the run panel');
});

test('invalid previews keep errors visible and still scroll the receipt', async () => {
  const panel = await read('../src/RunSingleCasePanel.tsx');
  assert.match(panel, /preview != null/, 'receipt still renders for invalid previews');
  assert.doesNotMatch(panel, /dispatchEvent\([\s\S]*?\)[\s\S]*?else/, 'no collapse-request else-branch that fires without the guard');
});

test('receipt path touches no approval or execution primitive', async () => {
  const panel = await read('../src/RunSingleCasePanel.tsx');
  assert.doesNotMatch(panel, /executeApproval|runExecute|sweepExecute|doRun\(\)/, 'scroll/guard path never approves or starts');
});
