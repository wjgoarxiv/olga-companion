// 0.1.20 row 15: Settings "Connect AI tools" rows, rendered for real in both languages.
import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const codex = { product: 'codex', label: 'Codex', mode: 'file', path: 'C:\\Users\\me\\.codex\\config.toml', connected: false };
const claude = { product: 'claude-code', label: 'Claude Code', mode: 'command', path: null, connected: false };

test('a file-based tool shows its config path and Connect; once connected, Remove', async () => {
  const { renderAiToolRow } = await reviewNotesRenderer();
  const off = renderAiToolRow('en', codex);
  assert.match(off, /Codex/);
  assert.match(off, /config\.toml/);
  assert.match(off, />Connect</);
  assert.match(off, /a backup is kept/i);
  const on = renderAiToolRow('en', { ...codex, connected: true });
  assert.match(on, /Connected/);
  assert.match(on, />Remove</);
  assert.match(renderAiToolRow('ko', codex), />연결</);
});

test('Claude Code shows the command to paste, not a file write, and the remove-first command', async () => {
  const { renderAiToolRow } = await reviewNotesRenderer();
  const command = 'claude mcp add --scope user --env OLGA_BRIDGE_SECRET=abc --transport stdio olga-companion -- "x.exe" "--mcp"';
  const html = renderAiToolRow('en', claude, { kind: 'command', command, removeCommand: 'claude mcp remove --scope user olga-companion' });
  assert.match(html, /<textarea[^>]*readonly/i);
  assert.match(html, /claude mcp add --scope user/);
  assert.match(html, /paste it in a terminal/i);
  assert.match(html, /aria-label="Remove command for Claude Code"[^>]*>claude mcp remove/);
  assert.doesNotMatch(html, /config\.toml|settings\.json/);
  assert.match(renderAiToolRow('ko', claude), /명령어/);
});

test('a connected Claude Code row says the command is ready, not that it is connected', async () => {
  const { renderAiToolRow } = await reviewNotesRenderer();
  const html = renderAiToolRow('en', { ...claude, connected: true });
  assert.match(html, /Command ready/);
  assert.doesNotMatch(html, />Connected</);
  assert.match(renderAiToolRow('ko', { ...claude, connected: true }), /명령어 준비됨/);
});

test('Remove for Claude Code shows the remove command with its own label and no secret hint', async () => {
  const { renderAiToolRow } = await reviewNotesRenderer();
  const html = renderAiToolRow('en', claude, { kind: 'removeCommand', command: 'claude mcp remove --scope user olga-companion' });
  assert.match(html, /aria-label="Command to remove Claude Code"/);
  assert.match(html, /finish removing it/);
  assert.doesNotMatch(html, /holds a secret/);
});

test('a refusal is shown in the chosen language with the detail below, and leaves Connect available', async () => {
  const { renderAiToolRow } = await reviewNotesRenderer();
  const detail = 'The Codex config file could not be read, so it was left unchanged.';
  const html = renderAiToolRow('ko', codex, { kind: 'error', detail });
  assert.match(html, /role="alert"/);
  assert.match(html, /바꾸지 못했어요/);
  assert.match(html, /left unchanged/);
  assert.match(html, />연결</);
});

test('the result line is a live region that exists before any result', async () => {
  const { renderAiToolRow } = await reviewNotesRenderer();
  assert.match(renderAiToolRow('en', codex), /<p class="ai-tool-done" role="status"><\/p>/);
  assert.match(renderAiToolRow('en', codex, { kind: 'done', backup: null }), /role="status">Done\./);
});
