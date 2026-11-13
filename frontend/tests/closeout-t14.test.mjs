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
  if (Array.isArray(node)) return node.map((child) => renderElement(react, child, instance)).filter((value) => value !== null);
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

function findButton(tree, label) {
  for (const node of walk(tree)) {
    if (node?.type === 'button' && textOf(node).includes(label)) return node;
  }
  return null;
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

async function loadPanel(saveArtifactAs, revealSavedReport) {
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
  const StubButton = (props) => react.api.createElement('button', { onClick: props?.onClick }, props?.children);
  registry.set('./ui/Button', { __esModule: true, default: StubButton, Button: StubButton });
  registry.set('./nativeDialogRequest', { __esModule: true, createNativeDialogRequestId: () => 'request-1' });
  registry.set('./nativeDialogApi', { __esModule: true, saveArtifactAs, revealSavedReport });
  registry.set('./resultApi', {
    __esModule: true,
    evaluateFindings: async () => ({ pending: [], judgements: [] }),
    createFindingsReport: async () => ({ markdown: '# report', filename: 'report.md', artifact: 'artifact:fresh' }),
  });
  registry.set('./sessionFigures', { __esModule: true, sessionFigures: () => [] });
  const panel = run(await transpile('FindingsPanel.tsx'));
  return { react, FindingsPanel: panel.default };
}

const baseProps = {
  selected: { id: 'result-1', name: 'run.tpl', rel: 'run.tpl', origin: 'run', size: 1, suffix: '.tpl', modified_ns: 1, run_id: 'run-1' },
  variables: [{ variable: 'PT', position: 'POS_A' }],
  branches: [],
  genkeyHint: 'case.genkey',
  workspaceRoot: '/tmp/ws',
};

test('folder reveal appears only after a successful save', async () => {
  const revealed = [];
  const { react, FindingsPanel } = await loadPanel(
    async () => ({ status: 'selected', basename: 'report.md', size: 12, reveal_id: 'ab'.repeat(16) }),
    async (revealId) => { revealed.push(revealId); },
  );
  let tree = renderElement(react, { type: FindingsPanel, props: baseProps }, 'before');
  assert.equal(findButton(tree, '폴더에서 보기'), null);

  findButton(tree, '보고서 만들기').props.onClick();
  await flush();
  tree = renderElement(react, { type: FindingsPanel, props: baseProps }, 'before');
  const reveal = findButton(tree, '폴더에서 보기');
  assert.ok(reveal, 'the button follows a save that returned a reveal id');
  reveal.props.onClick();
  await flush();
  assert.deepEqual(revealed, ['ab'.repeat(16)]);
});

test('a cancelled save and a save without a reveal id leave the folder button hidden', async () => {
  const cancelled = await loadPanel(async () => ({ status: 'cancelled' }), async () => {});
  let tree = renderElement(cancelled.react, { type: cancelled.FindingsPanel, props: baseProps }, 'cancel');
  findButton(tree, '보고서 만들기').props.onClick();
  await flush();
  tree = renderElement(cancelled.react, { type: cancelled.FindingsPanel, props: baseProps }, 'cancel');
  assert.equal(findButton(tree, '폴더에서 보기'), null);

  const bare = await loadPanel(
    async () => ({ status: 'selected', basename: 'report.md', size: 4 }),
    async () => { throw new Error('must not reveal'); },
  );
  tree = renderElement(bare.react, { type: bare.FindingsPanel, props: baseProps }, 'bare');
  findButton(tree, '보고서 만들기').props.onClick();
  await flush();
  tree = renderElement(bare.react, { type: bare.FindingsPanel, props: baseProps }, 'bare');
  assert.equal(findButton(tree, '폴더에서 보기'), null);
  assert.match(textOf(tree), /저장됨: report.md/);
});
