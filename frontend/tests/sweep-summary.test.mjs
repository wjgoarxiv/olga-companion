import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('finished sweeps render a summary table and an overlay plot, never a launch control', async () => {
  const [status, api, summary] = await Promise.all([
    read('../src/RunSweepStatus.tsx'),
    read('../src/sweepApi.ts'),
    read('../src/SweepSummaryTable.tsx'),
  ]);
  assert.match(status, /SweepSummaryTable/, 'the status view embeds the summary table');
  assert.match(status, /TrendChart/, 'the overlay reuses the existing trend chart');
  assert.match(api, /\/api\/sweep\/summary/, 'the summary comes from a read-only GET route');
  assert.match(summary, /<table|<Table/, 'one table maps parameter values to outputs');
  assert.match(summary, /from '\.\/ui\/Table'|from "\.\/ui\/Table"/, 'the summary uses the shared Table primitive');
  assert.match(summary, /ariaLabel=\{t\('sweep\.summaryAria'\)\}/, 'the table is labelled');
  assert.doesNotMatch(summary, /sweepExecute|Approve/, 'the summary cannot launch or approve anything');
});
