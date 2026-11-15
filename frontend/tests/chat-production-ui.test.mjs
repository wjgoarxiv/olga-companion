import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('Chat uses the shared visible activity console and typed lifecycle evidence', async () => {
  const [chat, controller, stream, evidence, lifecycle] = await Promise.all([
    read('../src/ChatView.tsx'),
    read('../src/useChatController.ts'),
    read('../src/useChatStream.ts'),
    read('../src/EvidenceBlock.tsx'),
    read('../src/LifecycleEvidence.tsx'),
  ]);

  assert.match(chat, /import \{ ActivityLoader \} from '\.\/ui\/ActivityLoader'/);
  assert.match(chat, /<ActivityLoader[^>]*loadingLabel=\{props\.activity\.label\}/s);
  assert.match(chat, /props\.activity\.elapsed_ms/);
  assert.match(chat, /props\.activity\?\.can_cancel/);
  assert.match(stream, /useChatActivity/);
  assert.match(stream, /activity\.observe\(event\)/);
  assert.match(evidence, /<LifecycleEvidence name=\{name\} result=\{result\}/);
  for (const tool of ['simulation_setup', 'run_patrol', 'case_edit_plan', 'case_publish']) {
    assert.match(lifecycle, new RegExp(`case '${tool}'`));
  }
  assert.match(lifecycle, /result\.semantic_diff/);
  assert.match(lifecycle, /result\.text_diff/);
  assert.match(lifecycle, /result\.failed_step/);
  assert.match(lifecycle, /<progress/);
  assert.match(lifecycle, /<details className="evidence-audit"/);
  assert.match(lifecycle, /requires_fresh_approval/);
});

test('case publication approval shows the exact bound action without invented run defaults', async () => {
  const [card, ko] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(card, /request\.name === 'case_publish'/);
  for (const field of ['transaction_id', 'compiled_hash', 'destination_rel', 'context_generation']) {
    assert.match(card, new RegExp(`request\\.args\\.${field}`));
  }
  assert.doesNotMatch(card, /request\.args\.timeout_s \?\? 3600/);
  assert.match(card, /t\('approval\.approvePublish'\)/);
  assert.match(ko, /'approval\.approvePublish': '승인하고 게시'/);
});

test('CaseSpec planning has dedicated validation, topology, geometry, and audit evidence', async () => {
  const [lifecycle, caseSpec] = await Promise.all([
    read('../src/LifecycleEvidence.tsx'),
    read('../src/CaseSpecEvidence.tsx'),
  ]);
  assert.match(lifecycle, /'case_spec_validate'/);
  assert.match(lifecycle, /'case_spec_compile'/);
  assert.match(caseSpec, /function CaseSpecEvidence/);
  assert.match(caseSpec, /사례 명세가 맞습니다/);
  assert.match(caseSpec, /t\('casespec\.conn'\)/);
  assert.match(caseSpec, /t\('casespec\.shape'\)/);
  assert.match(caseSpec, /publishable/);
  assert.match(caseSpec, /spec_hash/);
  assert.match(caseSpec, /compiled_hash/);
});

test('run approval reads exact runtime facts from server display rather than model args', async () => {
  const approval = await read('../src/ApprovalCard.tsx');
  assert.match(approval, /request\.display/);
  assert.doesNotMatch(approval, /request\.args\.runtime_id/);
  assert.doesNotMatch(approval, /request\.args\.executable/);
  assert.doesNotMatch(approval, /request\.args\.output_target/);
  assert.doesNotMatch(approval, /request\.args\.source_sha256/);
  assert.match(approval, /runDisplayReady/);
  assert.match(approval, /cardLifecycle !== 'awaiting-approval' \|\| !runDisplayReady/);
});

test('visual QA fixture mounts real lifecycle, approval, table, plot, and artifact components', async () => {
  const fixture = await read('./lifecycle-visual-fixture.tsx');
  for (const component of ['LifecycleEvidence', 'ApprovalCard', 'SeriesTable', 'TrendChart', 'ArtifactCard']) {
    assert.match(fixture, new RegExp(`<${component}`));
  }
  for (const state of ['case_spec_compile', 'case_edit_plan', 'run_patrol']) {
    assert.match(fixture, new RegExp(state));
  }
  assert.match(fixture, /state="patrol-failure"/);
  assert.match(fixture, /state="run-approval"/);
});

test('Chat evidence owns local overflow, natural CJK wrapping, and sticky approval actions', async () => {
  const [tools, responsive] = await Promise.all([
    read('../src/styles/chat-tools.css'),
    read('../src/styles/chat-responsive.css'),
  ]);

  assert.match(tools, /\.evidence-prose\s*\{[^}]*word-break:\s*keep-all/s);
  assert.match(tools, /\.evidence-table-viewport\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(tools, /\.evidence-table-viewport th\s*\{[^}]*white-space:\s*nowrap/s);
  assert.match(tools, /\.approval-actions\s*\{[^}]*position:\s*sticky/s);
  assert.match(responsive, /\.approval-actions[^}]*min-height:\s*44px/s);
});

test('approval buttons carry a sticky what-where line so evidence survives the fold', async () => {
  const [card, tools] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    read('../src/styles/chat-tools.css'),
  ]);
  assert.match(card, /approval-sticky-summary/, 'a summary line lives inside the sticky action bar');
  assert.match(card, /destination_rel/, 'the summary names the publish destination file');
  assert.match(card, /t\('approval\.stickyAsIs'\)/, 'the summary states the original is untouched');
  assert.match(
    tools,
    /\.approval-actions\s*\{[^}]*flex-wrap:\s*wrap/s,
    'the sticky bar wraps so the summary sits above the buttons',
  );
  assert.match(
    tools,
    /\.approval-actions\s*>\s*\.approval-sticky-summary\s*\{[^}]*flex:[^}]*100%/s,
    'the summary takes the full row even under the mobile button rule',
  );
});

test('repeated result-variable identities still receive unique React keys', async () => {
  // Rows live in the picker since the todo-9 surface split; keys stay unique.
  const picker = await read('../src/VariablePicker.tsx');
  assert.match(picker, /shown\.map\(\(v, index\) =>/);
  assert.match(picker, /key=\{`\$\{resultVariableKey\(v\)\}:\$\{index\}`\}/);
});
