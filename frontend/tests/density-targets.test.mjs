import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* N3 owner decision (2026-10-30): "조작성도 불편하고". Compact is the default
 * density with 32px targets (WCAG 2.2 AA asks 24px); comfortable keeps 44px. */

test('compact is the default density with a 32px target token and comfortable keeps 44px', async () => {
  const [base, appearance] = await Promise.all([read('../src/styles/base.css'), read('../src/appearance.ts')]);

  const root = base.match(/:root\s*\{[^]*?\n\}/);
  assert.ok(root, 'the root block exists');
  assert.match(root[0], /--tgt:\s*calc\(32px \* var\(--ui-scale\)\)/, 'the default (compact) target is 32px at 100 %');
  const comfortable = base.match(/\[data-density="comfortable"\]\s*\{[^}]*\}/s);
  assert.ok(comfortable, 'the comfortable block exists');
  assert.match(comfortable[0], /--tgt:\s*calc\(44px \* var\(--ui-scale\)\)/, 'comfortable targets stay 44px');
  assert.doesNotMatch(base, /\[data-density="compact"\]/, 'compact needs no override block: it is the root default');
  const floors = [...base.matchAll(/--tgt:\s*calc\((\d+)px/g)].map((m) => Number(m[1]));
  assert.ok(floors.length >= 2 && floors.every((px) => px >= 32), `no target token drops below 32px (${floors})`);
  assert.match(appearance, /parseDensity\(readLocalStorage\(DENSITY_KEY\)\)\s*\?\?\s*'compact'/, 'a fresh profile starts compact');
});

test('32px chrome buttons expose a 44px hit area in both densities', async () => {
  const [primitives, workbench] = await Promise.all([
    read('../src/styles/primitives.css'),
    read('../src/styles/workbench.css'),
  ]);

  for (const [name, css] of [['ui-iconbutton', primitives], ['wb-btn', workbench]]) {
    const expanded = new RegExp(`\\.${name}::after\\s*\\{[^}]*inset:\\s*-6px`, 's');
    const floor = new RegExp(`\\.${name}[^{]*\\{[^}]*min-height:\\s*var\\(--tgt\\)`, 's');
    assert.ok(
      expanded.test(css) || floor.test(`${css}`),
      `${name} reaches 44px via an expanded hit area or the target token`,
    );
  }
});
