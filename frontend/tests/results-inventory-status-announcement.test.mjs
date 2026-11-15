import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('result inventory announces scan, refresh, and completion as one atomic status', async () => {
  const rail = await readFile(new URL('../src/ResultsInventoryRail.tsx', import.meta.url), 'utf8');
  assert.match(
    rail,
    /<strong className="rv-files-title" role="status" aria-live="polite" aria-atomic="true">/,
    'the changing inventory title must be one non-interruptive atomic announcement',
  );
});
