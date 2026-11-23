// 0.1.27 small fixes: the edit lesson counts only the copy saved during the lesson, the new-case
// starter asks for a case the bundled air-water table can run, and the i18n allowlist holds no
// entry that matches nothing in the source.
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { tutorialStepSatisfied } from '../src/tutorialTour.mjs';
import { translate } from '../src/i18n/index.ts';

const srcDir = new URL('../src/', import.meta.url);
const src = (name) => readFileSync(new URL(name, srcDir), 'utf8');

test('the edit lesson step needs the copy saved in this lesson, not an older demo.editN', () => {
  const base = { demoCaseName: 'demo.genkey', savedEditName: 'demo.edit3.genkey' };
  assert.equal(tutorialStepSatisfied('edit-endtime', { ...base, activeCaseName: 'demo.edit3.genkey' }), true);
  assert.equal(tutorialStepSatisfied('edit-endtime', { ...base, activeCaseName: 'demo.edit1.genkey' }), false, 'an older copy is rejected');
  assert.equal(tutorialStepSatisfied('edit-endtime', { demoCaseName: 'demo.genkey', savedEditName: null, activeCaseName: 'demo.edit1.genkey' }), false, 'no save yet');
  assert.equal(tutorialStepSatisfied('edit-endtime', { ...base, activeCaseName: 'other.edit3.genkey' }), false);
});

test('a successful edit save announces its file so the tour can tell it apart', () => {
  assert.match(src('shell/workspaceEvents.ts'), /export const CASE_EDIT_SAVED_EVENT = 'olga:case-edit-saved'/);
  assert.match(src('CaseEditTable.tsx'), /new CustomEvent\(CASE_EDIT_SAVED_EVENT, \{ detail: \{ rel: receipt\.destination_rel \} \}\)/);
  const host = src('TutorialHost.tsx');
  assert.match(host, /addEventListener\(CASE_EDIT_SAVED_EVENT/);
  assert.match(host, /savedEditName/);
  const onOpen = host.slice(host.indexOf('const onOpen = () => {'), host.indexOf('window.addEventListener(TUTORIAL_OPEN_EVENT'));
  assert.match(onOpen, /setSavedEditName\(null\)/, 'a restarted tour forgets the previous lesson\'s copy');
});

test('no starter prompt offers CO2, in the catalogs or the component fallback', () => {
  const keys = [...src('i18n/ko.ts').matchAll(/^  '([^']+)':/gm)].map((m) => m[1]).filter((k) => /starter|example/i.test(k));
  const texts = keys.flatMap((k) => [translate('ko', k), translate('en', k)]);
  assert.ok(texts.length > 0);
  for (const text of texts) assert.doesNotMatch(text, /CO2|CO₂|이산화탄소|carbon dioxide/i, 'no starter offers CO2');
  assert.doesNotMatch(src('EmptyState.tsx'), /CO2|CO₂|이산화탄소/, 'no CO2 in the starter fallback');
});

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : /\.(tsx?|mjs|json)$/.test(name) ? [p] : [];
  });
}

test('every plain i18n allowlist entry still appears in the source, and each has a reason', () => {
  const allow = JSON.parse(readFileSync(new URL('../i18n-allowlist.json', import.meta.url), 'utf8'));
  const sources = walk(srcDir.pathname).map((p) => readFileSync(p, 'utf8')).join('\n');
  const plain = allow.allow.filter((entry) => !/^\/.*\/[a-z]*$/.test(entry));
  assert.deepEqual(plain.filter((entry) => !sources.includes(entry)), [], 'stale plain entries');
  assert.deepEqual(Object.keys(allow.reasons).filter((key) => !allow.allow.includes(key)), [], 'reasons for removed entries');
});
