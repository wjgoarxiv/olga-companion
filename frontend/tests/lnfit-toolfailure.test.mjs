import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('lnfit tool: failed error-only result shows the reason line only', async () => {
  const src = await read('../src/ToolUnit.tsx');
  assert.match(src, /isErrorOnly/, 'ToolUnit names the error-only case');
  assert.match(src, /status === 'failed' && isErrorOnly/, 'failed error-only suppresses the evidence block');
  assert.match(src, /\{hasBody && open && <EvidenceBlock/, 'structured payloads still render evidence');
});
