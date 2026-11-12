import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('(g) the provider form offers only backend-supported protocols', async () => {
  const [connections, api] = await Promise.all([
    read('../src/ApiKeyConnections.tsx'),
    read('../src/apiKeyApi.ts'),
  ]);
  assert.doesNotMatch(connections + api, /anthropic-messages/, 'the backend supports only openai-chat and openai-responses');
});

test('(h) the findings panel resets when the selected file changes', async () => {
  const layout = await read('../src/ResultsLayout.tsx');
  assert.match(layout, /<FindingsPanel key=\{selected\.id\}/, 'stale thresholds never judge a newly selected file');
});

test('(i) the refused title names the publish case only', async () => {
  const card = await read('../src/ApprovalCard.tsx');
  assert.doesNotMatch(card, /title="게시 거부됨"/, 'no unconditional publish wording on run approvals');
  assert.match(card, /isPublish \? t\('approval\.publishRefused'\) : t\('approval\.runRefused'\)/, 'runs name their own refusal');
});

test('(j) the card holds finalizing until resume ends', async () => {
  const continuation = await read('../src/useApprovalContinuation.ts');
  assert.match(
    continuation,
    /lifecycle: 'finalizing'[\s\S]*?await resume\(request, generation\)/s,
    'resume runs before any terminal settlement',
  );
  assert.match(
    continuation,
    /await resume\(request, generation\);\s*return;\s*\}\s*finishApproval\(request, state, execution\.result\)/s,
    'terminal settlement happens only after resume, never before it',
  );
});
