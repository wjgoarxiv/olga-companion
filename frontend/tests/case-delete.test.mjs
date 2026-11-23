// 0.1.23 row 3: a case is deleted from the Explorer only through its review card, and only to the Recycle Bin.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const review = (linked) => ({ rel: 'sub/a.genkey', name: 'a.genkey', size: 2048, sha256: 'f'.repeat(64), linked_results: linked });

test('the card names the file, its size, its results and the Recycle Bin, in Korean', async () => {
  const r = await reviewNotesRenderer();
  const html = r.renderCaseDeleteFacts('ko', review(3));
  assert.match(html, /a\.genkey/);
  assert.match(html, /2\.0 KB/);
  assert.match(html, /이 사례로 실행한 결과 3개는 그대로 남습니다/);
  assert.match(html, /휴지통/);
  assert.match(html, /<button[^>]*>휴지통으로 보내기<\/button>/);
  assert.match(html, /<button[^>]*>취소<\/button>/);
});

test('the card says when no results came from the case, in English', async () => {
  const r = await reviewNotesRenderer();
  const html = r.renderCaseDeleteFacts('en', review(0));
  assert.match(html, /No run results came from this case/);
  assert.match(html, /Recycle Bin/);
  assert.match(html, /<button[^>]*>Move to Recycle Bin<\/button>/);
});

test('a changed file shows why nothing was deleted', async () => {
  const r = await reviewNotesRenderer();
  assert.match(r.renderCaseDeleteFacts('ko', review(0), 'stale_source'), /파일이 바뀌어 지우지 않았습니다/);
  assert.match(r.renderCaseDeleteFacts('en', review(0), 'stale_source'), /The file changed, so nothing was deleted/);
});

test('approve sends exactly the reviewed hash and the workspace generation', async () => {
  const api = await read('../src/caseDeleteApi.ts');
  const fn = api.match(/export async function deleteCase[\s\S]*?\n}\n/)?.[0] ?? '';
  assert.match(fn, /'\/api\/case-delete'/);
  assert.match(fn, /sha256: review\.sha256/);
  assert.match(fn, /context_generation: contextGeneration/);
  assert.match(fn, /approved: true/);
  const card = await read('../src/CaseDeleteCard.tsx');
  assert.match(card, /reviewCaseDelete\(rel\)/);
  assert.match(card, /deleteCase\(review, reviewedGeneration\)/);
});

test('approve sends the generation the card was reviewed under, and a workspace switch reopens the card', async () => {
  const card = await read('../src/CaseDeleteCard.tsx');
  assert.match(card, /const \[reviewedGeneration\] = useState\(contextGeneration\)/);
  const panel = await read('../src/shell/ExplorerPanel.tsx');
  assert.match(panel, /<CaseDeleteCard\s+key=\{`\$\{contextGeneration\}:\$\{item\.rel\}`\}/);
});

test('deleting the open case resets the screens the same way closing it does, then refreshes the file list (PVT D1)', async () => {
  const card = await read('../src/CaseDeleteCard.tsx');
  assert.match(card, /onDone\(result\.closed\)/);
  const panel = await read('../src/shell/ExplorerPanel.tsx');
  assert.match(panel, /onDone=\{\(closed\) => \{ setDeleting\(null\); onChanged\(closed\); \}\}/);
  const app = await read('../src/App.tsx');
  assert.match(app, /onChanged=\{\(closed\) => void \(closed \? pickCase\(null\)\.then\(refreshWorkspace\) : refreshWorkspace\(\)\)\}/);
});

test('the Explorer offers Delete only for a .genkey and opens the card, never deleting directly', async () => {
  const panel = await read('../src/shell/ExplorerPanel.tsx');
  assert.match(panel, /item\.suffix === '\.genkey' && \(\s*<button[^>]*role="menuitem"[^>]*onClick=\{\(\) => \{ setItemMenu\(null\); setDeleting\(item\.rel\); \}\}/);
  assert.match(panel, /<CaseDeleteCard/);
  assert.doesNotMatch(panel, /deleteCase\(/);
});
