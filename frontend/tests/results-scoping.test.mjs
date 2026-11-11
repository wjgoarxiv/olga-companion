import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  UNKNOWN_ROOT,
  isForeignResult,
  normalizeWorkspaceRoot,
  scopeRootOf,
  splitByRoot,
} from '../src/resultScoping.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* W2-L3b (M8): results-rail scoping. Hidden-other applies FIRST at
   workspace-root level (root ?? 'unknown' → other); the case-only
   checkbox then applies WITHIN the visible pool; both counts derive
   from the post-root pool. Never hardcode counts: expectations below
   are computed from the fixture arrays. */

// Fixture: two current-root receipts, one foreign receipt on the same
// case, one workspace file. Invented names only.
const CURRENT = 'C:\\work\\case-a';
const FOREIGN = 'D:\\other\\case-b';
const fixture = () => ([
  { id: 'run:1/a.tpl', origin: 'run', name: 'a.tpl', source_name: 'case-a', root: CURRENT },
  { id: 'run:2/b.tpl', origin: 'run', name: 'b.tpl', source_name: 'case-a', root: CURRENT },
  { id: 'run:3/c.tpl', origin: 'run', name: 'c.tpl', source_name: 'case-a', root: FOREIGN },
  { id: 'workspace:d/p.ppl', origin: 'workspace', name: 'p.ppl', source_name: null },
]);

test('root normalization equates separator, case, and trailing-slash variants', () => {
  assert.equal(normalizeWorkspaceRoot('C:\\work\\case-a\\'), normalizeWorkspaceRoot('c:/work/case-a'));
  assert.equal(normalizeWorkspaceRoot(null), null);
  assert.equal(normalizeWorkspaceRoot(''), null);
});

test('missing root scopes as unknown, unknown counts as other', () => {
  assert.equal(scopeRootOf({}), UNKNOWN_ROOT);
  assert.equal(scopeRootOf({ root: null }), UNKNOWN_ROOT);
  assert.equal(scopeRootOf({ root: CURRENT }), CURRENT);
  assert.ok(isForeignResult({ origin: 'run' }, CURRENT), 'rootless run receipt is foreign (fail closed)');
  assert.ok(isForeignResult({ origin: 'run', root: FOREIGN }, CURRENT), 'foreign root is foreign');
  assert.ok(!isForeignResult({ origin: 'run', root: CURRENT }, CURRENT), 'same root is visible');
  assert.ok(!isForeignResult({ origin: 'workspace', root: 'anything' }, CURRENT), 'workspace files are always visible');
});

test('hidden-other splits first; opt-in reveals all', () => {
  const all = fixture();
  const closed = splitByRoot(all, CURRENT, false);
  assert.deepEqual(closed.visible.map((r) => r.id), ['run:1/a.tpl', 'run:2/b.tpl', 'workspace:d/p.ppl']);
  assert.equal(closed.hiddenOther, all.filter((r) => r.root === FOREIGN).length);
  assert.ok(!closed.visible.some((r) => r.source_name === 'case-a' && r.root === FOREIGN), 'zero foreign source rows in the visible pool');
  const open = splitByRoot(all, CURRENT, true);
  assert.equal(open.visible.length, all.length);
  assert.equal(open.hiddenOther, 0);
});

test('unwired rail (no current root) shows everything', () => {
  const all = fixture();
  const { visible, hiddenOther } = splitByRoot(all, null, false);
  assert.equal(visible.length, all.length);
  assert.equal(hiddenOther, 0);
});

test('case-only composes within the post-root pool', async () => {
  const rail = await read('../src/ResultsInventoryRail.tsx');
  assert.match(rail, /from '\.\/resultScoping'/, 'rail uses the scoping helper');
  assert.match(rail, /caseResults[\s\S]{0,400}?rootVisible|rootVisible[\s\S]{0,400}?caseResults/, 'case filter reads the post-root pool');
  assert.match(rail, /totalCount:?\s*\w+|totalCount,/, 'case/total counts exist');
  assert.doesNotMatch(rail, /caseResults = activeCaseName \? results\.filter/, 'case filter no longer reads the unscoped pool');
});

test('toggle renders the owner copy with a computed count', async () => {
  const rail = await read('../src/ResultsInventoryRail.tsx');
  assert.match(rail, /results\.hiddenOther/, 'hidden toggle key');
  assert.match(rail, /results\.otherShown/, 'shown toggle key');
  assert.match(rail, /aria-pressed/, 'toggle exposes pressed state');
  assert.doesNotMatch(rail, /hiddenOther.*\d+건|N건/, 'no hardcoded hidden counts in the rail');
});

test('empty and truncation behavior survive scoping', async () => {
  const rail = await read('../src/ResultsInventoryRail.tsx');
  assert.match(rail, /results\.noOutputs/, 'all-hidden resolves to the noOutputs empty state');
  assert.match(rail, /title=\{`?\$\{f\.name\}/, 'full title tooltips kept');
  assert.match(rail, /case-name-stem/, 'stem-first middle-truncate kept');
});

test('owner copy is verbatim in ko and en', async () => {
  const [ko, en] = await Promise.all([read('../src/i18n/ko.ts'), read('../src/i18n/en.ts')]);
  assert.match(ko, /'results\.hiddenOther': '다른 작업 공간 \{count\}건 숨김 · 모두 보기'/, 'ko verbatim');
  assert.match(en, /'results\.hiddenOther': '\{count\} from other workspaces hidden · Show all'/, 'en verbatim');
  assert.match(ko, /'results\.otherShown': /, 'ko shown key');
  assert.match(en, /'results\.otherShown': /, 'en shown key');
});
