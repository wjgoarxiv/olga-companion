import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('the workbench fits the viewport: document never scrolls, regions scroll inside', async () => {
  const [base, wb, shell] = await Promise.all([
    read('../src/styles/base.css'),
    read('../src/styles/workbench.css'),
    read('../src/styles/shell.css'),
  ]);
  assert.match(base, /html,\s*body\s*\{[^}]*height:\s*100%/s, 'app fills the viewport');
  assert.match(wb, /html,\s*body\s*\{[^}]*overflow:\s*hidden/s, 'html/body never scroll');
  assert.match(wb, /\.wb\s*\{[^}]*height:\s*100dvh/s, 'shell is viewport-tall');
  assert.match(wb, /\.wb-mid\s*\{[^}]*min-height:\s*0/s, 'the mid row can shrink');
  assert.match(shell, /\.shell-main\s*\{[^}]*grid-area:\s*centre[^}]*min-height:\s*0/s, 'centre owns its grid cell and shrinks');
  assert.match(wb, /\.wb-centre-tabs > \.ui-tabs > \.ui-tabpanel\s*\{[^}]*min-height:\s*0;[^}]*overflow:\s*auto/s, 'the tab strip height is subtracted; the panel scrolls inside');
  assert.match(shell, /\.chat\s*\{[^}]*min-height:\s*0/s, 'the dock chat shrinks');
});

test('timeline children wrap or shrink instead of scrolling the dock sideways', async () => {
  const [shell, messages] = await Promise.all([
    read('../src/styles/shell.css'),
    read('../src/styles/chat-messages.css'),
  ]);
  assert.match(shell, /\.timeline > \*\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%/s, 'timeline children shrink');
  assert.match(shell, /\.chat > \.timeline\s*\{[^}]*min-width:\s*0;[^}]*min-height:\s*0/s, 'the timeline itself shrinks inside the dock');
  assert.match(messages, /\.md pre\s*\{[^}]*max-width:\s*100%;[^}]*overflow-x:\s*auto/s, 'code blocks scroll inside themselves');
  assert.match(messages, /\.bubble\.assistant \.md p\s*\{[^}]*overflow-wrap:\s*anywhere/s, 'assistant paragraphs emergency-break');
  assert.match(messages, /\.md a\s*\{[^}]*overflow-wrap:\s*anywhere/s, 'long links wrap');
  assert.match(messages, /\.msg\s*\{[^}]*max-width:\s*100%/s, 'messages stay within the timeline');
});

test('the Run palette entry matches the Run view name', async () => {
  const [en, ko] = await Promise.all([read('../src/i18n/en.ts'), read('../src/i18n/ko.ts')]);
  assert.ok(en.includes(`'shell.cmdGoRuns': 'Go to Run',`), 'en matches the Run view');
  assert.ok(ko.includes(`'nav.run': '실행'`), 'ko tab label is the reference');
  assert.ok(ko.includes(`'shell.cmdGoRuns': '실행으로 이동'`), 'ko matches the Run tab label');
});
