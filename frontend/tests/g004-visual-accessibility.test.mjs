import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const root = process.cwd();
const baseCss = fs.readFileSync(path.join(root, 'frontend/src/styles/base.css'), 'utf8');
const chatToolsCss = fs.readFileSync(path.join(root, 'frontend/src/styles/chat-tools.css'), 'utf8');

function token(css, name) {
  const match = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'));
  assert.ok(match, `missing --${name}`);
  return match[1];
}

function luminance(hex) {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((value) => value <= 0.04045
    ? value / 12.92
    : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(foreground, background) {
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

test('muted metadata tokens retain WCAG AA contrast on canvas and cloud', () => {
  for (const name of ['mute', 'stone']) {
    const foreground = token(baseCss, name);
    assert.ok(contrast(foreground, token(baseCss, 'canvas')) >= 4.5, `--${name} fails on canvas`);
    assert.ok(contrast(foreground, token(baseCss, 'cloud')) >= 4.5, `--${name} fails on cloud`);
  }
});

test('definition-list wrapper flattening is scoped to generic evidence rows', () => {
  assert.doesNotMatch(chatToolsCss, /(?:^|\n)dl > div\s*\{/);
  assert.match(chatToolsCss, /\.evidence-block dl > div\s*\{\s*display:\s*contents;/);
});

test('composer exposes an explicit keyboard focus-visible treatment', () => {
  assert.match(chatToolsCss, /\.composer textarea:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--info\)/s);
});
