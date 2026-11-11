import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function luminance(hex) {
  const [r, g, b] = [0, 2, 4].map((at) => {
    const v = Number.parseInt(hex.slice(at + 1, at + 3), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function themeBlock(css, theme) {
  if (theme === 'light') return css.slice(0, css.indexOf('@media (prefers-color-scheme: dark)'));
  const start = css.indexOf(':root[data-theme="dark"]');
  return css.slice(start);
}

function token(block, name) {
  const match = block.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
  assert.ok(match, `${name} resolves to a hex token`);
  return match[1];
}

for (const theme of ['light', 'dark']) {
  test(`case surface text keeps 4.5:1 contrast in ${theme} mode`, async () => {
    const css = await read('../src/styles/base.css');
    const block = themeBlock(css, theme);
    const canvas = token(block, '--panel');
    for (const text of ['--ink', '--ink-2', '--mute']) {
      const value = ratio(token(block, text), canvas);
      assert.ok(value >= 4.5, `${text} on --panel is ${value.toFixed(2)}:1 in ${theme}`);
    }
  });
}

test('case surface styles read theme tokens, never hard-coded light colours', async () => {
  const [workspaceCss, promptsCss] = await Promise.all([
    read('../src/styles/workspace.css'),
    read('../src/styles/workbench-prompts.css'),
  ]);
  for (const [name, css] of [['workspace.css', workspaceCss], ['workbench-prompts.css', promptsCss]]) {
    assert.doesNotMatch(css, /var\(--canvas\)|var\(--cloud\)|var\(--charcoal\)/, `${name} no longer reads legacy light roles`);
    assert.doesNotMatch(css, /#[fF][bBfF][bBfF][bBfF]9|#f1f2ef|#353835/, `${name} has no hard-coded light colours`);
  }
});
