import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { filterResultFiles } from '../src/resultPresentation.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('result inventory search resolves repeated filenames by run identity without mutating source order', async () => {
  const first = {
    id: 'run:first/case.tpl',
    name: 'case.tpl',
    origin: 'run',
    rel: 'first/case.tpl',
    run_id: 'c8c9a12e17c4',
    run_state: 'completed',
    run_ok: true,
  };
  const second = {
    id: 'run:second/case.ppl',
    name: 'case.ppl',
    origin: 'run',
    rel: 'second/case.ppl',
    run_id: '15f9c1750b8b',
    run_state: 'failed',
    run_ok: false,
  };
  const source = [first, second];

  assert.deepEqual(filterResultFiles(source, 'c8c9 tpl'), [first]);
  assert.deepEqual(filterResultFiles(source, 'failed 15f9'), [second]);
  assert.deepEqual(source, [first, second], 'filtering never reorders or mutates source inventory');

  const [rail, prompts, promptCss] = await Promise.all([
    read('../src/ResultsInventoryRail.tsx'),
    read('../src/ResultsPrompts.tsx'),
    read('../src/styles/workbench-prompts.css'),
  ]);
    assert.match(rail, /useExplorerFilter/, 'the rail filters from the single explorer store');
  assert.match(rail, /t\('results\.filteredBy', \{ filter \}\)/, 'the active explorer filter is announced');
  assert.doesNotMatch(rail, /rv-inventory-filter/, 'the duplicate rail filter input is gone');
  assert.match(rail, /t\('results\.countFiltered', \{ shown: shownResults\.length, total: results\.length \}\)/);
  assert.match(rail, /t\('results\.noMatch'\)/);
  assert.doesNotMatch(prompts, /rail on the left/, 'responsive guidance cannot assume a desktop rail position');
  assert.match(promptCss, /@media \(max-width: 760px\)[\s\S]*?\.rv-selection-state\s*\{\s*margin:\s*0;/);
});
