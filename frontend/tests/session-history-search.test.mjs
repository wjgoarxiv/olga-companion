import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { filterSessions } from '../src/sessionSearch.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('chat history search matches every token across title and full session ID without reordering', () => {
  const sessions = [
    { session_id: '5a71813b-aaaa', title: 'OLGA session' },
    { session_id: '82fec345-bbbb', title: 'G009 direct debug' },
    { session_id: '4e0ccaa2-cccc', title: 'CO2 line' },
  ];

  assert.deepEqual(filterSessions(sessions, 'direct 82fe'), [sessions[1]]);
  assert.deepEqual(filterSessions(sessions, 'CCCC co2'), [sessions[2]]);
  assert.deepEqual(filterSessions(sessions, '  '), sessions);
  assert.deepEqual(filterSessions(sessions, 'missing'), []);
});

test('chat history rail exposes labelled search without a misleading raw total', async () => {
  const [menu, css] = await Promise.all([
    read('../src/SessionMenu.tsx'),
    read('../src/styles/session-rail.css'),
  ]);

  assert.match(menu, /type="search"[\s\S]*aria-label=\{t\('history\.searchAria'\)\}[\s\S]*placeholder=\{t\('history\.searchPlaceholder'\)\}/);
  assert.match(menu, /filterSessions\(sessions, query\)/);
  assert.match(menu, /query\.trim\(\) \? t\('history\.searchResults'\) : t\('history\.savedConversations'\)/);
  assert.doesNotMatch(menu, /toLocaleString\(\)/, 'history chrome must not advertise an unhelpful raw storage count');
  assert.match(menu, /t\('history\.noChatsMatch'\)[\s\S]*t\('history\.tryTitleOrId'\)/);
  assert.match(css, /\.session-search\s*\{[^}]*min-height:\s*44px/s);
});
