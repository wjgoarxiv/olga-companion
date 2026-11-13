import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const ev = (type, data = {}) => ({ type, data });

// ai-dock-and-neo-fx todo 4: the answer in progress is a collapsed, unconfirmed draft.

test('draft events grow the draft; the final text, done, error, a tool call or an approval replace it', async () => {
  const { reduceDraft } = await import('../src/chatDraft.mjs');
  let draft = '';
  draft = reduceDraft(draft, ev('draft', { text: '안녕' }));
  draft = reduceDraft(draft, ev('draft', { text: '하세요' }));
  assert.equal(draft, '안녕하세요');
  assert.equal(reduceDraft(draft, ev('phase', { phase: 'model' })), draft, 'a phase frame leaves the draft alone');
  assert.equal(reduceDraft(draft, ev('thinking', { text: 'reasoning' })), draft, 'reasoning never joins the draft');
  for (const type of ['text', 'done', 'error', 'tool_call', 'approval_required', 'open']) {
    assert.equal(reduceDraft(draft, ev(type, { text: 'final' })), '', `${type} clears the draft`);
  }
});

test('an empty or whitespace draft shows nothing; a long draft keeps its tail', async () => {
  const { draftToShow, DRAFT_LIMIT } = await import('../src/chatDraft.mjs');
  assert.equal(draftToShow(''), null);
  assert.equal(draftToShow('  \n '), null);
  assert.equal(draftToShow('partial'), 'partial');
  const long = `${'a'.repeat(DRAFT_LIMIT)}tail`;
  const shown = draftToShow(long);
  assert.ok(shown.length <= DRAFT_LIMIT && shown.endsWith('tail'), 'the newest text stays visible');
});

test('the wait phases are distinct: previous answer, model, then running', async () => {
  const { eventActivityPhase, presentChatActivity, localizeActivity } = await import('../src/progressPresentation.mjs');
  assert.equal(eventActivityPhase(ev('open')), 'waiting_model');
  assert.equal(eventActivityPhase(ev('phase', { phase: 'queued' })), 'queued');
  assert.equal(eventActivityPhase(ev('phase', { phase: 'model' })), 'waiting_model');
  assert.equal(eventActivityPhase(ev('draft', { text: 'x' })), 'running');
  assert.equal(eventActivityPhase(ev('tool_call')), 'running');
  assert.equal(eventActivityPhase(ev('done')), 'finalizing');
  const base = { started_at_ms: 0, now_ms: 1000, cancellable: true, reduced_motion: false };
  const queued = presentChatActivity({ ...base, phase: 'queued' });
  const waiting = presentChatActivity({ ...base, phase: 'waiting_model' });
  assert.notEqual(queued.label, waiting.label);
  assert.equal(waiting.can_cancel, true, 'the turn can be stopped while the model is awaited');
  const t = (key) => ({ 'chat.phase.queued': '다른 답변이 끝나기를 기다리는 중', 'chat.phase.waitingModel': '모델 응답 기다리는 중' })[key] ?? key;
  assert.equal(localizeActivity(queued, t).label, '다른 답변이 끝나기를 기다리는 중');
  assert.equal(localizeActivity(waiting, t).label, '모델 응답 기다리는 중');
  assert.equal(localizeActivity({ ...queued, phase: 'running', label: 'Running' }, t).label, 'chat.phase.running', 'running is localized too');
  assert.equal(localizeActivity({ ...queued, phase: 'unknown', label: 'Other' }, t).label, 'Other', 'a phase without a key keeps its label');
});

test('the SSE client and event types know draft and phase', async () => {
  const [sse, types] = await Promise.all([read('../src/sseClient.ts'), read('../src/types.ts')]);
  for (const name of ['draft', 'phase']) {
    assert.match(sse, new RegExp(`case '${name}':`), `sseClient passes ${name} through`);
    assert.match(types, new RegExp(`\\| '${name}'`), `AgentEventType includes ${name}`);
  }
});

test('ChatView shows a closed details toggle only while a draft exists, labelled unconfirmed', async () => {
  const view = await read('../src/ChatView.tsx');
  const block = view.match(/<details[^>]*className="draft-toggle"[\s\S]*?<\/details>/);
  assert.ok(block, 'a details.draft-toggle exists');
  assert.doesNotMatch(block[0].match(/<details[^>]*>/)[0], /\bopen\b/, 'closed by default');
  assert.match(view, /props\.busy && draftToShow\(props\.draft\)/, 'rendered only while busy and a draft exists');
  assert.match(block[0], /t\('chat\.draft\.show'\)/);
  assert.match(block[0], /t\('chat\.draft\.unconfirmed'\)/);
  assert.match(block[0], /aria-live="off"/, 'no screen-reader flood from token updates');
  assert.match(block[0], /tabIndex=\{0\}/, 'the scrolling draft body is keyboard reachable');
  assert.doesNotMatch(block[0], /<Markdown/, 'a half-written answer is plain text, not parsed markdown');
});

test('the stream hook keeps the draft, drops it when the turn ends, is stopped or the chat changes, and plays no cue', async () => {
  const [hook, stream, controller, dock] = await Promise.all([
    read('../src/useChatDraft.ts'),
    read('../src/useChatStream.ts'),
    read('../src/useChatController.ts'),
    read('../src/shell/ChatDockView.tsx'),
  ]);
  assert.match(hook, /reduceDraft/);
  assert.match(hook, /const \[draft, setDraft\] = useState\(''\)/);
  assert.doesNotMatch(hook + controller, /sound/, 'no cue from draft or text handling');
  assert.match(stream, /draft\.observe\(event\)/, 'every stream event reaches the draft reducer');
  const finish = stream.match(/finally \{[\s\S]*?\n    \}\n  \}/)[0];
  assert.match(finish, /draft\.clear\(\)/, 'a finished, failed or stopped turn drops the draft');
  assert.match(stream.match(/function invalidate\(\)[\s\S]*?\n  \}/)[0], /draft\.clear\(\)/, 'a chat or workspace switch drops the draft');
  assert.match(controller, /draft: stream\.draft/);
  assert.match(dock, /draft=\{chat\.draft\}/);
  assert.match(dock, /localizeActivity\(chat\.activity, t\)/, 'the wait phases show their ko/en label');
});

test('draft and phase strings exist in ko and en', async () => {
  const [ko, en] = await Promise.all([read('../src/i18n/ko.ts'), read('../src/i18n/en.ts')]);
  const want = {
    'chat.draft.show': ['작성 중인 답변 보기', 'Show answer in progress'],
    'chat.draft.unconfirmed': ['초안 — 확정 아님', 'Draft, not final'],
    'chat.phase.queued': ['다른 답변이 끝나기를 기다리는 중', 'Waiting for the previous answer to finish'],
    'chat.phase.waitingModel': ['모델 응답 기다리는 중', 'Waiting for the model'],
  };
  for (const [key, [koText, enText]] of Object.entries(want)) {
    assert.ok(ko.includes(`'${key}': '${koText}'`), `ko ${key}`);
    assert.ok(en.includes(`'${key}': '${enText}'`), `en ${key}`);
  }
});

test('the draft box is a bounded scroll region with token sizes', async () => {
  const css = await read('../src/styles/chat-messages.css');
  const body = css.match(/\.draft-body\s*\{([^}]*)\}/);
  assert.ok(body, '.draft-body is styled');
  assert.match(body[1], /overflow-y:\s*auto/);
  assert.match(body[1], /max-height:/);
  assert.match(body[1], /font-size:\s*var\(--fs-s\)/);
  assert.match(body[1], /white-space:\s*pre-wrap/);
});

// Follow-up: the activity loader and the stop control read in the UI language with a visible edge.

const PHASES = ['connecting', 'queued', 'waiting_model', 'running', 'finalizing', 'completed', 'failed', 'cancelled'];

test('every activity phase label and the elapsed text come from the dictionary in ko and en', async () => {
  const { translate } = await import('../src/i18n/index.ts');
  const { presentChatActivity, localizeActivity } = await import('../src/progressPresentation.mjs');
  const base = { started_at_ms: 0, now_ms: 4000, cancellable: true, reduced_motion: false };
  const labels = { ko: new Set(), en: new Set() };
  for (const locale of ['ko', 'en']) {
    const t = (key, vars) => translate(locale, key, vars);
    for (const phase of PHASES) {
      const label = localizeActivity(presentChatActivity({ ...base, phase }), t).label;
      assert.doesNotMatch(label, /^chat\./, `${locale} ${phase} has a dictionary entry`);
      if (locale === 'ko') assert.doesNotMatch(label, /[A-Za-z]/, `ko ${phase} label "${label}" has no English`);
      labels[locale].add(label);
    }
    const elapsed = t('chat.elapsed', { seconds: '4.0' });
    assert.ok(elapsed.includes('4.0'), `${locale} elapsed text carries the seconds`);
    if (locale === 'ko') assert.doesNotMatch(elapsed.replace(/4\.0/, ''), /[A-Za-z]/, `ko elapsed "${elapsed}" has no English`);
  }
  for (const locale of ['ko', 'en']) assert.equal(labels[locale].size, PHASES.length, `${locale} phase labels are all distinct`);
});

test('ChatView builds the elapsed text from the dictionary, not an English literal', async () => {
  const view = await read('../src/ChatView.tsx');
  assert.match(view, /t\('chat\.elapsed'/);
  assert.doesNotMatch(view, /s elapsed/);
});

test('the stop control keeps a visible edge: a bordered button, not a quiet one', async () => {
  const view = await read('../src/ChatView.tsx');
  const stop = view.match(/<Button[^>]*className="stop"[\s\S]*?<\/Button>/)[0];
  assert.doesNotMatch(stop, /variant="quiet"/, 'a quiet button has a transparent border');
  assert.match(stop, /variant="secondary"/, 'secondary carries the shared 3:1 hairline edge');
});
