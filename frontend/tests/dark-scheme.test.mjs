import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('dark scheme has OS preference plus explicit theme override and no bright hardcodes', async () => {
  const [base, chat, tools, results, shell, statusbar, session, workspace, settingsView] = await Promise.all([
    read('../src/styles/base.css'),
    read('../src/styles/chat-messages.css'),
    read('../src/styles/chat-tools.css'),
    read('../src/styles/results.css'),
    read('../src/styles/shell.css'),
    read('../src/styles/statusbar.css'),
    read('../src/styles/session-rail.css'),
    read('../src/styles/workspace.css'),
    read('../src/SettingsView.tsx'),
  ]);

  assert.match(base, /:root\s*\{[^}]*color-scheme:\s*light/s, 'bare root holds the light paper default');
  assert.match(base, /--bg:\s*#e1e2e7/, 'light default is the Terminalcore Day canvas');
  assert.match(
    base,
    /@media \(prefers-color-scheme:\s*dark\)[\s\S]*?:root:not\(\[data-theme="light"\]\)/s,
    'OS dark preference applies unless light is forced',
  );
  assert.match(base, /:root\[data-theme="dark"\][\s\S]*?--ink:\s*#c0caf5/s, 'explicit dark override carries the Night ink');
  assert.match(base, /:root\[data-theme="dark"\][\s\S]*?--select:\s*#7aa2f7/s, 'signal blue is the Night selection fill');
  assert.match(base, /:root\[data-theme="dark"\][\s\S]*?--accent-2:\s*#9ece6a/s, 'phosphor green is the Night second accent');
  assert.match(base, /:root\[data-theme="light"\]/, 'explicit light override exists');
  assert.match(settingsView, /settings\.themeSystem/, 'Settings offers the System theme choice');
  assert.match(settingsView, /settings\.themeLight/, 'Settings offers the Light theme choice');
  assert.match(settingsView, /settings\.themeDark/, 'Settings offers the Dark theme choice');
  assert.match(settingsView, /appearance\.theme|useAppearance/, 'Settings drives the theme through the appearance store');

  for (const [name, css] of Object.entries({ chat, tools, results, shell, statusbar, session, workspace })) {
    assert.doesNotMatch(css, /#f9f9f7|#f1f2ef|#f6f7f4|#f3f4f1|#eceeea|#fbfbfa|#f8f9f6|#f5f6f3/i, `${name} keeps no bright hardcoded surface`);
  }
  assert.match(chat, /var\(--surface-raised\)/, 'assistant bubble reads the raised token');
  assert.match(chat, /var\(--bubble-user\)/, 'user bubble is one flat tokenized wash');
  assert.doesNotMatch(chat, /gradient/, 'no gradient anywhere in the chat bubbles');
  assert.match(chat, /var\(--on-bubble-user\)/, 'user bubble text uses a dedicated label token');
  assert.match(base, /--on-bubble-user:\s*#1f2335/, 'Day bubble label is the Day ink');
  assert.match(base, /:root\[data-theme="dark"\][\s\S]*?--on-bubble-user:\s*#c0caf5/s, 'Night bubble label is the Night ink');
  assert.match(results, /var\(--series-1\)/, 'profile series color follows the scheme');
  assert.match(shell, /\.wb-activity \.ui-iconbutton\[aria-pressed="true"\]/, 'the pressed activity reads as tactile depth in both schemes');
});

test('flowpath palette lives in tokens with dark-safe values, xAI matches provider rows', async () => {
  const [base, viewer, settings] = await Promise.all([
    read('../src/styles/base.css'),
    read('../src/FlowpathGeometryViewer.tsx'),
    read('../src/styles/settings.css'),
  ]);
  for (let n = 1; n <= 7; n += 1) {
    assert.match(base, new RegExp(`--pipe-${n}:`), `pipe token ${n} is defined`);
  }
  assert.match(
    base,
    /:root\[data-theme="dark"\][\s\S]*?--pipe-1:/s,
    'dark pipe overrides exist',
  );
  assert.doesNotMatch(viewer, /#006d77|#bc6c25|#5a189a|#0077b6|#9b2226|#2a9d8f|#6c757d/, 'no hardcoded palette hexes remain');
  assert.match(viewer, /var\(--pipe-/, 'sections reference pipe tokens');
  assert.match(
    settings,
    /\.xai-connect \.ui-button\s*\{[^}]*justify-self:\s*stretch/s,
    'the xAI action spans the full provider-row width like its sibling selects',
  );
});
