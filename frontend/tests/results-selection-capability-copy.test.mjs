import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('result selection prompt distinguishes shared inspection from TPL-only actions', async () => {
  const prompts = await readFile(new URL('../src/ResultsPrompts.tsx', import.meta.url), 'utf8');
  assert.match(
    prompts,
    /description=\{t\('results\.pickDesc'\)\}/,
  );
  assert.doesNotMatch(
    prompts,
    /Inspect variables and lineage for any result/,
    'beginner-facing selection copy stays Korean; TPL/PPL tokens stay verbatim',
  );
});
