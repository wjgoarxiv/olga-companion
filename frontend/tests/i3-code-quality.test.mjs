import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readRunSource } from './run-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('run and sweep polling failures downgrade live claims to last-known supervision', async () => {
  const [run, panel] = await Promise.all([
    readRunSource(),
    read('../src/RunFailurePanel.tsx'),
  ]);

  assert.match(run, /const \[supervisionUnknown, setSupervisionUnknown\] = useState\(false\)/);
  assert.match(run, /const \[sweepSupervisionUnknown, setSweepSupervisionUnknown\] = useState\(false\)/);
  assert.match(run, /await session\.runStatus\(id\);[\s\S]*setSupervisionUnknown\(next\.state === 'supervision_unknown'\)/);
  assert.match(run, /session\.runStatus\(id\)[\s\S]*catch \(e\)[\s\S]*setSupervisionUnknown\(true\)[\s\S]*err\(e, true\)/);
  assert.match(run, /await session\.sweepStatus\(id\);[\s\S]*setSweepSupervisionUnknown\(next\.state === 'supervision_unknown'\)/);
  assert.match(run, /session\.sweepStatus\(id\)[\s\S]*catch \(e\)[\s\S]*setSweepSupervisionUnknown\(true\)[\s\S]*err\(e, true\)/);
  assert.match(run, /async function doCancel\(\)[\s\S]*setSupervisionUnknown\(true\)[\s\S]*await session\.runCancel[\s\S]*setSupervisionUnknown\(cancelled\.state === 'supervision_unknown'\)/);
  assert.match(run, /async function doSweepCancel\(\)[\s\S]*setSweepSupervisionUnknown\(true\)[\s\S]*await session\.sweepCancel[\s\S]*setSweepSupervisionUnknown\(cancelled\.state === 'supervision_unknown'\)/);
  assert.match(run, /tone=\{monitoringUnknown \? 'info' : 'error'\}/);
  assert.match(run, /t\('run\.sweepLastKnown'\)/);
  assert.match(run, /\{sweepSupervisionUnknown && \([\s\S]*<OperationStatus[\s\S]*title=\{t\('run\.sweepSupervisionTitle'\)\}/);
  assert.match(run, /<RunFailurePanel status=\{status\} historical=\{statusSource === 'history'\} supervisionUnknown=\{supervisionUnknown\}/);

  assert.match(panel, /readonly supervisionUnknown\?: boolean/);
  assert.doesNotMatch(panel, /status\.state === 'running'[\s\S]{0,80}live/);
  assert.match(panel, /supervisionUnknown\s*\?\s*t\('run\.lineageLastKnown'\)/);
  assert.doesNotMatch(panel, /supervisionUnknown \? 'Live status'/);
  assert.match(panel, /supervisionUnknown && \([\s\S]*<OperationStatus[\s\S]*title=\{t\('run\.errSupervision'\)\}/);
});

test('run and sweep execute use immediate owned single-flight locks beside request epochs', async () => {
  const run = await readRunSource();

  assert.match(run, /import \{ createRequestEpoch, createSingleFlight \} from '\.\/requestEpoch'/);
  assert.match(run, /runExecuteLockRef = useRef\(createSingleFlight\(\)\)/);
  assert.match(run, /sweepExecuteLockRef = useRef\(createSingleFlight\(\)\)/);
  assert.match(run, /async function doRun\(\)[\s\S]*const lockId = runExecuteLockRef\.current\.begin\(\);[\s\S]*if \(lockId == null\) return;[\s\S]*await session\.runExecute/);
  assert.match(run, /async function doSweepRun\(\)[\s\S]*const lockId = sweepExecuteLockRef\.current\.begin\(\);[\s\S]*if \(lockId == null\) return;[\s\S]*await session\.sweepExecute/);
  assert.match(run, /finally \{[\s\S]*runExecuteLockRef\.current\.end\(lockId\)/);
  assert.match(run, /finally \{[\s\S]*sweepExecuteLockRef\.current\.end\(lockId\)/);
  assert.match(run, /mountedRef\.current = false;[\s\S]*runExecuteLockRef\.current\.reset\(\);[\s\S]*sweepExecuteLockRef\.current\.reset\(\)/);
});

test('workspace topology requests cannot overwrite a newer selection or commit after unmount', async () => {
  const [workspace, panel, app] = await Promise.all([
    read('../src/WorkspaceView.tsx'),
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/App.tsx'),
  ]);

  assert.match(workspace, /import \{ createWorkspaceHydration \} from '\.\/workspaceCaseOpen'/);
  assert.match(workspace, /hydrationRef = useRef<ReturnType<typeof createWorkspaceHydration>/);
  assert.match(workspace, /fetchTopology: session\.fetchTopology/);
  assert.match(workspace, /onStart:[\s\S]*setSelected\(c\.rel\)[\s\S]*setTopo\(null\)[\s\S]*setLoading\(true\)/);
  assert.match(workspace, /onSuccess: setTopo/);
  assert.match(workspace, /onError: \(cause\) => setError\(cause\.message\)/);
  assert.match(workspace, /onSettled: \(\) => setLoading\(false\)/);
  assert.match(workspace, /useEffect\(\(\) => \(\) => \{[\s\S]*hydrationRef\.current\?\.invalidate\(\)/, 'unmount invalidates clicks as well as effect hydration');
  assert.match(workspace, /const setup = hydrationRef\.current\?\.setup\(hydrationCase\);\s*return setup\?\.cleanup;/, 'effect cleanup owns its exact setup request');
  assert.match(panel, /if \(item\.suffix === '\.tab'\) \{[\s\S]*?return;/, 'non-topology files cannot enter the activating request path');
  assert.match(panel, /onPick\(item\.rel\)/, 'user selection uses the activating path');
  assert.match(app, /session\.setActiveCase\(rel/, 'activation reaches the server-side active case');
});

test('resolved approvals are neutral records while active dialogs own and restore focus', async () => {
  const [card, chat] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    read('../src/ChatView.tsx'),
  ]);

  assert.match(chat, /pending=\{props\.busy\}\s+resolved=\{item\.resolved\}/);
  assert.doesNotMatch(chat, /pending=\{props\.busy \|\| item\.resolved\}/);
  assert.match(card, /readonly resolved: boolean/);
  assert.match(card, /if \(resolved\) \{[\s\S]*<OperationStatus[\s\S]*tone="info"[\s\S]*title=\{t\('approval\.resolvedTitle'\)\}/);
  assert.match(card, /previousFocusRef = useRef<HTMLElement \| null>/);
  assert.match(card, /function restoreFocus\(\)/);
  assert.match(card, /role="alertdialog"/);
  assert.doesNotMatch(card, /autoFocus/);
  assert.match(card, /ref=\{approveButtonRef\}/);
  assert.match(card, /aria-label=\{t\('approval\.title'\)\}/);
  assert.doesNotMatch(card, /Approval (?:approved|rejected)/i);
});

test('shared Button visuals stay in controls while run, results, and prompt consumers keep layout only', async () => {
  const [controls, run, results, prompts] = await Promise.all([
    read('../src/styles/controls.css'),
    read('../src/styles/run.css'),
    read('../src/styles/results.css'),
    read('../src/styles/workbench-prompts.css'),
  ]);
  const visualProperty = /(?:^|;)\s*(?:color|background|border(?:-color|-radius)?|font(?:-size|-weight)?|cursor|opacity)\s*:/m;
  const block = (css, selector) => {
    const match = css.match(new RegExp(selector + '\\s*\\{([^}]*)\\}'));
    assert.ok(match, `missing ${selector} rule`);
    return match[1];
  };

  for (const [css, selector] of [
    [run, '\\.run-btn'],
    [run, '\\.run-go'],
    [run, '\\.run-actions \\.stop, \\.sweep-controls \\.stop'],
    [prompts, '\\.workbench-prompt-footer \\.ui-button'],
    [results, '\\.result-export'],
  ]) assert.doesNotMatch(block(css, selector), visualProperty, `${selector} must not override shared visuals`);

  assert.doesNotMatch(run, /\.(?:run-btn|run-go)(?::hover|:disabled)|\.run-actions \.stop:hover|\.sweep-controls \.stop:hover/);
  assert.doesNotMatch(results, /\.result-export(?::hover|:disabled)/);
  assert.doesNotMatch(prompts, /\.workbench-prompt-footer \.ui-button(?::hover|:disabled)/);
  assert.match(controls, /\.ui-button:disabled\s*\{[^}]*color:\s*var\(--btn-disabled-text\)[^}]*background:\s*var\(--btn-disabled-bg\)[^}]*border:\s*1px solid var\(--btn-disabled-border\)/s);
  assert.doesNotMatch(controls, /#68686a/i);
});
