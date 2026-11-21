// A callback ref that calls focus() runs on every render, so each keystroke in a child input
// pulls focus back to the container (0.1.15: "유체 표 만들기" took one letter at a time).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const root = new URL('../src/', import.meta.url).pathname;
function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? files(p) : p.endsWith('.tsx') ? [p] : [];
  });
}

test('no inline callback ref moves focus on render', () => {
  const offenders = files(root).filter((p) => /ref=\{\(\w+\)\s*=>\s*\{?[^}]*\.focus\(/.test(readFileSync(p, 'utf8')));
  assert.deepEqual(offenders.map((p) => p.slice(root.length)), []);
});

test('the fluid-table and pipe-table dialogs focus once on open', () => {
  for (const name of ['shell/FluidTableFlow.tsx', 'shell/PipeTableWizard.tsx']) {
    const source = readFileSync(join(root, name), 'utf8');
    assert.match(source, /useEffect\(\(\) => \{[^}]*focus\(\{ preventScroll: true \}\)[^}]*\}, \[\]\)/, name);
  }
});
