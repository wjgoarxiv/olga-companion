import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('chat actions are touch-safe through the comfortable-density token', async () => {
  const [tool, toolsCss, workbenchCss] = await Promise.all([
    read('../src/ToolUnit.tsx'),
    read('../src/styles/chat-tools.css'),
    read('../src/styles/workbench.css'),
  ]);

  assert.match(
    tool,
    /aria-label=\{hasBody[\s\S]*?t\(open \? 'tool\.ariaOpen' : 'tool\.ariaClosed', \{ name, state: statusLabel \}\)[\s\S]*?t\('tool\.ariaPlain', \{ name, state: statusLabel \}\)/,
    'tool headers expose an action, target, and current lifecycle state',
  );
  assert.match(
    toolsCss,
    /@media \(max-width:\s*760px\)[\s\S]*?\.tool-head\s*\{[^}]*min-height:\s*44px/s,
    'mobile tool disclosure targets meet the 44px product touch standard',
  );
  assert.match(
    workbenchCss,
    /\.chat-head-actions\s+\.new-chat\s*\{[^}]*min-height:\s*var\(--tgt\)/s,
    'new-chat meets the same touch standard through the comfortable-density token',
  );
});

test('chat audit affordances meet 44px at every width; message actions surface on touch', async () => {
  const [toolsCss, messagesCss] = await Promise.all([
    read('../src/styles/chat-tools.css'),
    read('../src/styles/chat-messages.css'),
  ]);

  assert.match(
    toolsCss,
    /\.tool-head\s*\{[^}]*min-height:\s*44px/s,
    'tool disclosure targets meet 44px on desktop too, not only under the mobile query',
  );
  assert.match(
    toolsCss,
    /\.evidence-audit summary[^{]*\{[^}]*min-height:\s*44px/s,
    'evidence summaries meet the same 44px target as the tool header',
  );
  assert.match(
    messagesCss,
    /@media[^{]*\(pointer:\s*coarse\)[^{]*\{[\s\S]*?\.msg-actions\s*\{[^}]*opacity:\s*1/s,
    'message actions are always visible on coarse pointers',
  );
  assert.match(
    messagesCss,
    /@media[^{]*\(pointer:\s*coarse\)[^{]*\{[\s\S]*?\.msg-action\s*\{[^}]*min-height:\s*44px/s,
    'message actions meet 44px where hover does not exist',
  );
});
