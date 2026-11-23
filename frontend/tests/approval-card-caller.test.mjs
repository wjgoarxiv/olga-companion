// 0.1.20 row 14: a card an outside AI tool asked for says so; an in-app card says nothing extra.
import test from 'node:test';
import assert from 'node:assert/strict';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';
import { rehydrateTimeline } from '../src/timeline.ts';

const request = { name: 'fluids_starter_tab', call_id: 'bridge-1', pending_id: 'p'.repeat(32), args: { tab_rel: 'air_water.tab' } };

test('the card names the outside tool that asked, in both languages', async () => {
  const render = await approvalCardRenderer();
  assert.match(render('en', { ...request, caller: 'Claude Code' }), /Asked by Claude Code from outside the app/);
  assert.match(render('ko', { ...request, caller: 'Claude Code' }), /Claude Code가 앱 밖에서 요청했어요/);
  assert.doesNotMatch(render('en', request), /Asked by/);
});

test('the caller survives the reload from chat history', () => {
  const items = rehydrateTimeline([
    { record: 'approval', ...request, state: 'pending', lifecycle: 'awaiting-approval', actionable: true, caller: 'Codex' },
  ]);
  const card = items.find((item) => item.kind === 'approval');
  assert.equal(card.request.caller, 'Codex');
});

test('a reloaded bridge card shows its text in the app language when both are stored (0.1.20 PVT)', async () => {
  const { setLocale } = await import('../src/i18n/index.ts');
  const displays = { ko: { fields: [{ key: 'table_kind', value: '범용 공기-물 표' }] }, en: { fields: [{ key: 'table_kind', value: 'Generic air-water table' }] } };
  const record = { record: 'approval', ...request, state: 'pending', lifecycle: 'awaiting-approval', actionable: true, caller: 'Claude Code', display: displays.en, displays };
  setLocale('ko');
  assert.equal(rehydrateTimeline([record]).find((item) => item.kind === 'approval').request.display.fields[0].value, '범용 공기-물 표');
  setLocale('en');
  assert.equal(rehydrateTimeline([record]).find((item) => item.kind === 'approval').request.display.fields[0].value, 'Generic air-water table');
});
