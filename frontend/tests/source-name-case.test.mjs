// 0.1.20 PVT: StopRemedy.tsx next to stopRemedy.mjs built on Linux but broke the Windows build,
// where './StopRemedy' found the .mjs. No two source modules may differ only by letter case.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../src/', import.meta.url));

function modules(dir, prefix = '') {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (entry.isDirectory()) return modules(`${dir}${entry.name}/`, `${prefix}${entry.name}/`);
    // A .d.mts describes the .mjs of the same name; it is not a second module.
    if (entry.name.endsWith('.d.mts') || entry.name.endsWith('.d.ts')) return [];
    const base = entry.name.replace(/\.(tsx|ts|mjs|js|jsx)$/, '');
    return base === entry.name ? [] : [`${prefix}${base}`];
  });
}

test('no two source modules share a name that differs only by case', () => {
  const seen = new Map();
  const clashes = [];
  for (const name of modules(root)) {
    const key = name.toLowerCase();
    if (seen.has(key) && seen.get(key) !== name) clashes.push(`${seen.get(key)} / ${name}`);
    seen.set(key, name);
  }
  assert.deepEqual(clashes, []);
});
