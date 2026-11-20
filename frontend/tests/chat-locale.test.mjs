import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { chatRequestBody } from '../src/chatRequest.ts';
import { currentLocale, setLocale } from '../src/i18n/index.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('chat send includes locale ko by default and en after switching', async () => {
  const previous = currentLocale();
  setLocale('ko');
  try {
    assert.deepEqual(chatRequestBody('session-1', 'hi', currentLocale()), {
      session_id: 'session-1',
      message: 'hi',
      locale: 'ko',
    });
    setLocale('en');
    assert.deepEqual(chatRequestBody('session-1', 'hi', currentLocale()), {
      session_id: 'session-1',
      message: 'hi',
      locale: 'en',
    });
  } finally {
    setLocale(previous);
  }
  assert.equal(currentLocale(), previous);
});

test('the chat POST body carries the live locale while approvals stay untouched', async () => {
  const api = await read('../src/chatSessionApi.ts');
  assert.match(api, /chatRequestBody\(sessionId, message, currentLocale\(\)\)/, 'send path reads the live locale');
  assert.match(api, /from '\.\/i18n\/index\.ts'/, 'send path uses the shared locale store');
  const execute = api.slice(api.indexOf('/api/approvals/execute'), api.indexOf('/api/approvals/reject'));
  const resume = api.slice(api.indexOf('/api/approvals/resume'));
  assert.doesNotMatch(execute, /locale/, 'approval execute carries no locale');
  assert.doesNotMatch(resume, /locale/, 'approval resume carries no locale');
});
