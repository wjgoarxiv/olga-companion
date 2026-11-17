import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readRunSource } from './run-source.mjs';
import { readSessionSource } from './session-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('run detection client exposes the version-selection contract and optional case source', async () => {
  const api = await readSessionSource(import.meta.url);

  assert.match(api, /export interface OlgaDetection\b/, 'detection response has a named frontend contract');
  for (const field of ['detected', 'exe', 'kind', 'version', 'selection_status', 'rationale', 'required_version', 'candidates', 'alternatives', 'evidence']) {
    assert.match(api, new RegExp(`\\b${field}\\b`), `OlgaDetection includes ${field}`);
  }
  assert.match(api, /runDetect\(source\?: string\): Promise<OlgaDetection>/, 'case source is optional and the response is typed');
  assert.match(api, /URLSearchParams\(\{ source \}\)/, 'Windows paths are query-encoded instead of interpolated raw');
});

test('run cockpit waits for the active case and requests detection for that exact path', async () => {
  const run = await readRunSource();

  assert.match(
    run,
    /const activeCase = await session\.fetchActiveCase\(\)[\s\S]*if \(!activeCase\.path\)[\s\S]*session\.runDetect\(activeCase\.path\)/,
    'active case loading precedes case-aware detection'
  );
  assert.doesNotMatch(run, /fetch\(['"]\/api\/run\/detect/, 'RunView uses the typed client instead of a global raw fetch');
});

test('run cockpit explains version selection and fails closed when the required version is missing', async () => {
  const run = await readRunSource();
  const util = await read('../src/util.ts');

  assert.match(run, /detect\.version/, 'selected OLGA version is visible');
  assert.match(run, /launcherKindLabel\(detect\.kind/, 'launcher kind is visible');
  assert.match(run, /formatRunReasonParts\(detect/, 'selection rationale is visible');
  assert.match(run, /detect\.alternatives\.map/, 'installed alternatives are visible');
  assert.match(run, /!detect\.detected/, 'every undetected selection is treated as blocked');
  assert.match(run, /selection_status === 'missing_required_version'/, 'missing required version has an explicit blocked state');
  assert.match(run, /disabled=\{safetyOperationActive \|\| !runReady\}/, 'single-case execution fails closed');
  assert.match(run, /disabled=\{safetyOperationActive \|\| !runReady \|\| !sweepSpec\.trim\(\)\}/, 'sweep execution fails closed too');
  assert.match(run, /import \{ basename \} from '\.\/util'/, 'RunView uses the shared display-path helper');
  assert.match(util, /split\(\/\[[^\]]*\\\\[^\]]*\]\//, 'launcher basenames handle both Windows and POSIX separators');
  assert.doesNotMatch(run, /title=\{(?:detect|alternative)\.exe\}/, 'absolute launcher paths are not exposed in tooltips');
});

test('run cockpit visibly exposes path-free engine-authored case evidence', async () => {
  const run = await readRunSource();

  assert.match(run, /t\('run\.evidenceSummary'\)/, 'case evidence has a visible heading');
  assert.match(run, /detect\.evidence\.map/, 'every engine-authored evidence item is rendered');
  assert.match(run, /evidence\.source_type/, 'the evidence source kind is visible');
  assert.match(run, /evidence\.version/, 'the engine-authored version is visible');
  assert.match(run, /basename\(evidence\.path\)/, 'the evidence source is reduced to a basename');
  assert.match(run, /basename\(evidence\.input_file\)/, 'the evidence case is reduced to a basename');
  assert.doesNotMatch(run, /\{evidence\.(?:path|input_file)\}/, 'absolute evidence paths are never rendered');
  assert.doesNotMatch(run, /title=\{evidence\.(?:path|input_file)\}/, 'absolute evidence paths are not exposed in tooltips');
});

test('run approval pins the previewed runtime and active-case changes remount detection', async () => {
  const [app, centre, bar] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/CentreViews.tsx'),
    read('../src/shell/TitleBar.tsx'),
  ]);
  const run = await readRunSource();
  const api = await readSessionSource(import.meta.url);

  assert.match(app, /const contextKey = `\$\{workspaceContext\.generation\}:\$\{contextRevision\}`/);
  assert.match(centre, /<RunView\s+key=\{contextKey\}/, 'workspace/case changes remount the run cockpit');
  assert.match(bar, /onClick=\{onPreviewRun\}/, 'the title-bar preview action is wired');
  assert.doesNotMatch(bar, /executeApproval|runExecute|sweepExecute|session\.execute/, 'the title bar can never approve or start a run');
  assert.match(api, /selection_id/, 'preview and execution contracts carry a runtime selection id');
  assert.match(api, /runExecute\(source: string, candidateId: string, selectionId: string/, 'execution requires the previewed runtime candidate and selection id');
  assert.match(run, /runExecute\(active\.path,\s*preview\.candidate_id,\s*preview\.selection_id/, 'Run uses the runtime candidate and selection id returned by preview');
  assert.match(run, /disabled=\{blockedReason !== ''\}/, 'Run stays disabled until a suitable runtime preview exists');
  assert.match(run, /approveBlockedReason\(\{ operationActive: safetyOperationActive, runReady, preview, usedSelectionId/, 'the disabled state is derived from the same gate that names its reason');
  assert.match(run, /detect\.alternatives\.map/, 'selected and blocked states both expose alternatives');
  assert.match(run, /catch \(cause\)[\s\S]*setError/, 'detection failures surface instead of hanging silently');
});

test('chat and sweep approvals bind the exact reviewed runtime and plan', async () => {
  const run = await readRunSource();
  const api = await readSessionSource(import.meta.url);
  const chat = await read('../src/useChatController.ts');
  const card = await read('../src/ApprovalCard.tsx');
  const tools = await read('../../src/olga_companion/agent/tool_side_effects.py');

  assert.match(chat, /session\.executeApproval\([\s\S]*request\.pending_id,\s*sessions\.sessionId,\s*request\.call_id/, 'chat approval claims the server-stored call');
  assert.match(tools, /action_kind == "run_execute"[\s\S]*selection_id/, 'server approval payload binds the preview selection id');
  assert.match(tools, /action_kind == "sweep_execute"[\s\S]*plan_id/, 'server approval payload binds the sweep plan id');
  assert.match(api, /sweepExecute\(sweepId: string, planId: string\)/, 'direct sweep execution requires a reviewed plan id');
  assert.match(api, /plan_id:\s*planId/, 'sweep execute sends the plan id');
  assert.doesNotMatch(run, /sweepPreview \?\? await session\.sweepPreview/, 'Run sweep cannot preview and execute in one click');
  assert.match(run, /if \([^)]*!sweepPreview[^)]*\) return/, 'Run sweep requires an existing preview');
  assert.match(run, /sweepExecute\(sweepPreview\.sweep_id,\s*sweepPreview\.plan_id\)/, 'Run sweep executes the exact reviewed plan');
  assert.match(run, /disabled=\{safetyOperationActive \|\| !runReady \|\| !sweepPreview/, 'Run sweep stays disabled before preview');
  assert.match(card, /selection_id/, 'run approval displays the pinned runtime selection');
  assert.match(card, /plan_id/, 'sweep approval displays the pinned plan');
  assert.doesNotMatch(card, /approval-path|title=\{subject\}/, 'approval card does not expose an absolute source path');
});

test('run readiness clears invalid contexts while preserving compatible accepted evidence across retry failures', async () => {
  const run = await readRunSource();
  const api = await readSessionSource(import.meta.url);

  assert.match(api, /export interface RunPreview\b/, 'preview has a named response contract');
  assert.match(api, /override_version_mismatch/, 'override version mismatches are typed');
  assert.match(api, /override_not_found/, 'missing override selections use the backend canonical status');
  assert.doesNotMatch(api, /invalid_override/, 'the retired non-canonical override status is absent');
  assert.match(api, /strength:\s*'strong' \| 'stale'/, 'stale engine evidence is represented in the contract');
  assert.match(run, /useState<session\.RunPreview \| null>/, 'preview state consumes the typed contract');
  assert.match(run, /if \(!activeCase\.path\)[\s\S]*setPreview\(null\)[\s\S]*setStatus\(null\)/, 'a successful empty-context reload clears stale evidence');
  assert.match(run, /if \(!activeCase\.path\.toLowerCase\(\)\.endsWith\('\.genkey'\)\)[\s\S]*setPreview\(null\)[\s\S]*setStatus\(null\)/, 'a non-GENKEY selection cannot retain runnable evidence');
  assert.match(run, /setPreview\(\(accepted\) => accepted\?\.candidate_id === nextCandidateId \? accepted : null\)/, 'compatible preview evidence survives a successful context refresh');
  const detectionStart = run.indexOf('const detection = await session.runDetect');
  const historyStart = run.indexOf('const history = await session.fetchRunHistory', detectionStart);
  const detectionBlock = run.slice(detectionStart, historyStart);
  assert.match(detectionBlock, /catch \(cause\)[\s\S]*contextError = cause instanceof Error/);
  assert.doesNotMatch(detectionBlock, /setPreview\(null\)|setStatus\(null\)/, 'detection retry failure preserves the last accepted preview and receipt');
  assert.match(run, /endsWith\('\.genkey'\)/, 'only GENKEY active cases can become run-ready');
  assert.match(run, /t\('approval\.previewCommand'\)\}<\/Button>/, 'the preview control remains explicit');
  assert.match(run, /selectionBlocked \? t\('run\.altBlocked'\) : t\('run\.altOthers'\)/, 'alternatives are labelled for blocked and selected states');
});
