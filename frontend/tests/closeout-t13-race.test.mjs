import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

import { createRequestEpoch } from '../src/requestEpoch.mjs';

void createRequestEpoch;

const SRC = new URL('../src/', import.meta.url);

async function transpile(relativePath) {
  const source = await readFile(new URL(relativePath, SRC), 'utf8');
  return ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2020,
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
    },
    fileName: relativePath,
  }).outputText;
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const tick = () => new Promise((done) => setImmediate(done));
async function flush(rounds = 20) {
  for (let i = 0; i < rounds; i += 1) await tick();
}

function makeReact() {
  const hooksByInstance = new Map();
  let current = null;
  let hookCursor = 0;
  function useState(initial) {
    const hooks = hooksByInstance.get(current);
    const index = hookCursor++;
    if (!hooks[index]) hooks[index] = { value: initial };
    const slot = hooks[index];
    return [slot.value, (next) => { slot.value = typeof next === 'function' ? next(slot.value) : next; }];
  }
  function useRef(initial) {
    const hooks = hooksByInstance.get(current);
    const index = hookCursor++;
    if (!hooks[index]) hooks[index] = { current: initial };
    return hooks[index];
  }
  function createElement(type, config, ...children) {
    const props = { ...(config ?? {}) };
    if (children.length === 1) props.children = children[0];
    else if (children.length > 1) props.children = children;
    return { type, props };
  }
  const Fragment = Symbol.for('headless-test-fragment');
  return {
    hooksByInstance,
    api: { createElement, Fragment, useState, useRef, useEffect: () => undefined },
    jsxRuntime: {
      jsx: (type, props) => ({ type, props: props ?? {} }),
      jsxs: (type, props) => ({ type, props: props ?? {} }),
      Fragment,
    },
    beginRender(instance) {
      if (!hooksByInstance.has(instance)) hooksByInstance.set(instance, []);
      current = instance;
      hookCursor = 0;
    },
  };
}

function renderElement(react, node, instance) {
  if (node === null || node === undefined || node === false) return null;
  if (Array.isArray(node)) return node.map((child) => renderElement(react, child, instance)).filter((v) => v !== null);
  if (typeof node === 'string' || typeof node === 'number') return node;
  if (typeof node.type === 'function') {
    react.beginRender(instance);
    return renderElement(react, node.type(node.props ?? {}), instance);
  }
  if (node.type === react.api.Fragment) return renderElement(react, node.props?.children, instance);
  return { type: node.type, props: { ...(node.props ?? {}), children: renderElement(react, node.props?.children, instance) } };
}

function* walk(node) {
  if (node === null || node === undefined || node === false) return;
  if (typeof node === 'string' || typeof node === 'number') {
    yield node;
    return;
  }
  if (Array.isArray(node)) {
    for (const child of node) yield* walk(child);
    return;
  }
  yield node;
  const children = node.props?.children;
  if (Array.isArray(children)) {
    for (const child of children) yield* walk(child);
  } else if (children) {
    yield* walk(children);
  }
}

function textOf(node) {
  const parts = [];
  for (const item of walk(node)) {
    if (typeof item === 'string') parts.push(item);
  }
  return parts.join('');
}

const FINDINGS_KO = {
  'findings.title': '판정',
  'findings.lede': '파일의 값으로 기준을 확인해요. 숫자는 직접 입력하세요.',
  'findings.choose': '고르세요',
  'findings.numberPlaceholder': '숫자 입력',
  'findings.unitPlaceholder': '단위 입력',
  'findings.criterion': '기준',
  'findings.judge': '판정',
  'findings.judging': '판정 중…',
  'findings.makeReport': '보고서 만들기',
  'findings.makingReport': '보고서 만드는 중…',
  'findings.kind.pressure_drop': '압력강하',
  'findings.kind.liqc': '액체량(LIQC)',
  'findings.kind.slugging': '슬러그 횟수',
  'findings.kind.wax_hydrate': '하이드레이트·왁스 여유',
  'findings.field.inlet': '입구 위치',
  'findings.field.outlet': '출구 위치',
  'findings.field.maxDrop': '최대 강하',
  'findings.field.unit': '단위',
  'findings.field.branch': '브랜치',
  'findings.field.maxCount': '슬러그 최대 횟수',
  'findings.field.hydrateTemp': '하이드레이트 기준 온도',
  'findings.field.waxTemp': '왁스 기준 온도',
  'findings.field.pipe': '파이프',
  'findings.field.maxLitres': '액체 최대량(리터)',
  'findings.fillToJudge': '빈 칸을 채우면 판정할 수 있어요.',
  'findings.stillNeed': '아직 {missing} 입력이 필요해요.',
  'findings.needCaseFile': '사례 파일이 필요해요.',
  'findings.saveCancelled': '저장을 취소했습니다',
  'findings.folderFailed': '폴더를 열지 못했어요.',
  'findings.noVar': '이 파일에는 {required}가 없어요. {required}를 출력에 추가하세요.',
  'findings.hintPressureDrop': '.tpl 파일에서',
  'findings.hintLiqc': '.ppl 파일에서',
  'findings.hintSlugging': '.ppl 파일에서',
  'findings.hintWax': '.tpl이나 .ppl 파일에서',
  'findings.caseFileLabel': '사례 파일(.genkey)',
  'findings.genkeyPlaceholder': '예: case.genkey',
  'findings.pickBranch': '브랜치를 고르면 판정할 수 있어요. {hint} 브랜치를 고르세요.',
  'findings.showInFolder': '폴더에서 보기',
  'findings.savedFile': '저장됨:',
  'findings.passState': '통과',
  'findings.failState': '미달',
  'findings.evidence': '근거:',
};

async function loadPanel(stubs) {
  const react = makeReact();
  const registry = new Map();
  const localRequire = (name) => {
    if (name === 'react') return react.api;
    if (name === 'react/jsx-runtime') return react.jsxRuntime;
    if (registry.has(name)) return registry.get(name);
    throw new Error(`unexpected import: ${name}`);
  };
  const run = (code) => {
    const module = { exports: {} };
    new Function('require', 'module', 'exports', code)(localRequire, module, module.exports);
    return module.exports;
  };
  registry.set('./GlossaryTerm', { __esModule: true, default: (props) => props?.children });
  registry.set('./requestEpoch', { __esModule: true, createRequestEpoch });
  registry.set('./i18n/index.ts', { __esModule: true, useLocale: () => ({ t: (key) => FINDINGS_KO[key] ?? key, locale: 'ko', setLocale: () => {} }) });
  registry.set('./unitPreferences', { __esModule: true, unitChoicesForDimension: () => [] });
  registry.set('./formatUnit', { __esModule: true, formatUnit: (unit) => unit ?? '' });
  registry.set('./FindingsCriterionFields', run(await transpile('FindingsCriterionFields.tsx')));
  const StubButton = (props) => react.api.createElement('button', { onClick: props?.onClick, disabled: props?.disabled }, props?.children);
  registry.set('./ui/Button', { __esModule: true, default: StubButton, Button: StubButton });
  registry.set('./nativeDialogRequest', { __esModule: true, createNativeDialogRequestId: () => 'request-1' });
  registry.set('./nativeDialogApi', { __esModule: true, ...stubs.nativeDialogApi });
  registry.set('./resultApi', { __esModule: true, ...stubs.resultApi });
  registry.set('./sessionFigures', { __esModule: true, sessionFigures: () => [] });
  const panel = run(await transpile('FindingsPanel.tsx'));
  return { react, FindingsPanel: panel.default };
}

const baseProps = {
  selected: { id: 'result-1', name: 'run.tpl', rel: 'run.tpl', origin: 'run', size: 1, suffix: '.tpl', modified_ns: 1, run_id: 'run-1' },
  variables: [
    { variable: 'PT', position: 'POS_A' },
    { variable: 'PT', position: 'POS_B' },
    { variable: 'HOL', position: 'PIPE_X' },
    { variable: 'TM', position: 'POS_A' },
  ],
  branches: ['BR_A'],
  genkeyHint: 'case.genkey',
  workspaceRoot: '/tmp/ws',
};

function mount(react, FindingsPanel, instance = 'panel') {
  let tree = null;
  const refresh = () => {
    tree = renderElement(react, { type: FindingsPanel, props: baseProps }, instance);
    return tree;
  };
  refresh();
  return { refresh, current: () => tree };
}

function findButton(tree, label) {
  for (const node of walk(tree)) {
    if (node?.type === 'button' && textOf(node).includes(label)) return node;
  }
  throw new Error(`button not found: ${label}`);
}

function findInput(tree, label) {
  const matches = [];
  const visit = (node, ancestors) => {
    if (!node || typeof node === 'string' || typeof node === 'number') return;
    if (Array.isArray(node)) {
      node.forEach((child) => visit(child, ancestors));
      return;
    }
    if ((node.type === 'input' || node.type === 'select') && typeof node.props?.onChange === 'function') {
      const caption = ancestors
        .filter((a) => a?.type === 'label')
        .map((a) => textOf(a))
        .join(' ');
      if (caption.includes(label)) matches.push(node);
    }
    const children = node.props?.children;
    const next = [...ancestors, node];
    if (Array.isArray(children)) children.forEach((child) => visit(child, next));
    else if (children) visit(children, next);
  };
  visit(tree, []);
  assert.ok(matches.length > 0, `input not found: ${label}`);
  return matches[0];
}

function hasVerdict(tree) {
  for (const node of walk(tree)) {
    if (node?.type === 'div' && typeof node.props?.className === 'string' && node.props.className.includes('findings-verdict')) return true;
  }
  return false;
}

function hasSavedNote(tree) {
  return textOf(tree).includes('저장됨:');
}

test('(10) a judge response after a newer edit is ignored', async () => {
  const judgeCalls = [];
  let gate = deferred();
  const { react, FindingsPanel } = await loadPanel({
    nativeDialogApi: {},
    resultApi: {
      evaluateFindings: (criteria) => { judgeCalls.push(criteria); return gate.promise; },
      createFindingsReport: async () => { throw new Error('not under test'); },
    },
  });
  const view = mount(react, FindingsPanel);
  findInput(view.current(), '입구 위치').props.onChange({ target: { value: 'POS_A' } });
  findInput(view.current(), '출구 위치').props.onChange({ target: { value: 'POS_B' } });
  findInput(view.current(), '최대 강하').props.onChange({ target: { value: '5' } });
  view.refresh();
  findButton(view.current(), '판정').props.onClick();
  await tick();
  assert.equal(judgeCalls.length, 1, 'judge sent the pre-edit inputs');
  findInput(view.current(), '최대 강하').props.onChange({ target: { value: '9' } });
  view.refresh();
  gate.resolve({ pending: [], judgements: [{ verdict: 'PASS', threshold: { max_drop: 5 }, measured: {} }] });
  await flush();
  view.refresh();
  assert.equal(hasVerdict(view.current()), false, 'the late verdict never pairs with the newer inputs');
});

test('(10) a judge response without a newer edit still lands', async () => {
  const { react, FindingsPanel } = await loadPanel({
    nativeDialogApi: {},
    resultApi: {
      evaluateFindings: async () => ({ pending: [], judgements: [{ verdict: 'PASS', threshold: { max_drop: 5 }, measured: {} }] }),
      createFindingsReport: async () => { throw new Error('not under test'); },
    },
  });
  const view = mount(react, FindingsPanel);
  findInput(view.current(), '입구 위치').props.onChange({ target: { value: 'POS_A' } });
  findInput(view.current(), '출구 위치').props.onChange({ target: { value: 'POS_B' } });
  findInput(view.current(), '최대 강하').props.onChange({ target: { value: '5' } });
  view.refresh();
  findButton(view.current(), '판정').props.onClick();
  await flush();
  view.refresh();
  assert.equal(hasVerdict(view.current()), true, 'the current verdict still renders');
});

test('(10) a report staged before a newer edit never opens Save As', async () => {
  const saveCalls = [];
  let reportGate = deferred();
  const { react, FindingsPanel } = await loadPanel({
    nativeDialogApi: { saveArtifactAs: async (...args) => { saveCalls.push(args); return { status: 'selected', basename: 'report.md' }; } },
    resultApi: {
      evaluateFindings: async () => ({ pending: [], judgements: [{ verdict: 'PASS', threshold: {}, measured: {} }] }),
      createFindingsReport: () => reportGate.promise,
    },
  });
  const view = mount(react, FindingsPanel);
  findInput(view.current(), '입구 위치').props.onChange({ target: { value: 'POS_A' } });
  findInput(view.current(), '출구 위치').props.onChange({ target: { value: 'POS_B' } });
  findInput(view.current(), '최대 강하').props.onChange({ target: { value: '5' } });
  view.refresh();
  findButton(view.current(), '판정').props.onClick();
  await flush();
  view.refresh();
  assert.equal(hasVerdict(view.current()), true, 'a current verdict is available for the report');
  findButton(view.current(), '보고서 만들기').props.onClick();
  await tick();
  findInput(view.current(), '최대 강하').props.onChange({ target: { value: '9' } });
  view.refresh();
  reportGate.resolve({ markdown: '# report', filename: 'report.md', artifact: 'artifact:stale' });
  await flush();
  view.refresh();
  assert.equal(saveCalls.length, 0, 'the stale report never reaches the Save As dialog');
  assert.equal(hasSavedNote(view.current()), false, 'no saved note pairs with the newer inputs');
});

test('(10) a report without a newer edit still saves', async () => {
  const { react, FindingsPanel } = await loadPanel({
    nativeDialogApi: { saveArtifactAs: async () => ({ status: 'selected', basename: 'report.md' }) },
    resultApi: {
      evaluateFindings: async () => ({ pending: [], judgements: [{ verdict: 'PASS', threshold: {}, measured: {} }] }),
      createFindingsReport: async () => ({ markdown: '# report', filename: 'report.md', artifact: 'artifact:fresh' }),
    },
  });
  const view = mount(react, FindingsPanel);
  findInput(view.current(), '입구 위치').props.onChange({ target: { value: 'POS_A' } });
  findInput(view.current(), '출구 위치').props.onChange({ target: { value: 'POS_B' } });
  findInput(view.current(), '최대 강하').props.onChange({ target: { value: '5' } });
  view.refresh();
  findButton(view.current(), '판정').props.onClick();
  await flush();
  view.refresh();
  findButton(view.current(), '보고서 만들기').props.onClick();
  await flush();
  view.refresh();
  assert.equal(hasSavedNote(view.current()), true, 'the current report still saves');
});

test('(10) the panel uses one request epoch per flow', async () => {
  const panel = await readFile(new URL('../src/FindingsPanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /judgeRequestRef = useRef\(createRequestEpoch\(\)\)/);
  assert.match(panel, /reportRequestRef = useRef\(createRequestEpoch\(\)\)/);
  assert.match(panel, /judgeRequestRef\.current\.begin\(\)/);
  assert.match(panel, /reportRequestRef\.current\.begin\(\)/);
  assert.match(panel, /judgeRequestRef\.current\.isCurrent\(requestId\)/);
  assert.match(panel, /reportRequestRef\.current\.isCurrent\(requestId\)/);
  assert.match(panel, /invalidateRequests\(\)/);
});
