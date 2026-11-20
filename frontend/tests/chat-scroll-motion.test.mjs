import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { chatScrollBehavior } from '../src/chatScrollBehavior.mjs';

test('the chat glides only when neither the OS nor the app asks for less motion', () => {
  assert.equal(chatScrollBehavior({ systemReduced: false, motionAttr: 'subtle' }), 'smooth');
  assert.equal(chatScrollBehavior({ systemReduced: false, motionAttr: 'full' }), 'smooth');
  assert.equal(chatScrollBehavior({ systemReduced: false, motionAttr: null }), 'smooth');
});

test('the chat jumps when the OS prefers reduced motion', () => {
  assert.equal(chatScrollBehavior({ systemReduced: true, motionAttr: 'subtle' }), 'auto');
  assert.equal(chatScrollBehavior({ systemReduced: true, motionAttr: null }), 'auto');
});

test('the chat jumps when the app motion setting is off, even if the OS allows motion', () => {
  assert.equal(chatScrollBehavior({ systemReduced: false, motionAttr: 'off' }), 'auto');
});

test('useChatScroll no longer hard-codes a smooth scroll', () => {
  const source = readFileSync(new URL('../src/useChatScroll.ts', import.meta.url), 'utf8');
  assert.match(source, /chatScrollBehavior\(/);
  assert.doesNotMatch(source, /behavior:\s*'smooth'/);
});
