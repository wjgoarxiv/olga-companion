export const TUTORIAL_STORAGE_KEY = 'olga-companion.tutorial.v1';

export const TUTORIAL_OPEN_EVENT = 'olga:tutorial-open';

export const TUTORIAL_CHANGE_EVENT = 'olga:tutorial-change';

export const TUTORIAL_EVENTS = Object.freeze({
  WORKSPACE_CHOSEN: 'workspace-chosen',
  CASE_CREATED: 'case-created',
  VALIDATION_DONE: 'validation-done',
  VALIDATION_READ: 'validation-read',
  RUN_STARTED: 'run-started',
  RUN_FINISHED: 'run-finished',
  RESULTS_OPENED: 'results-opened',
  NO_OLGA: 'no-olga',
});

export const NO_OLGA_STEP_ID = 'run';

function step(id, event, statusKey, target = id) {
  return Object.freeze({ id, target, textKey: `tutorial.step.${id}`, event, statusKey });
}

/**
 * Copy per step lives under textKey: .title, .body (why, one line), .where, .done.
 * statusKey is the step-bar status line the user sees once the step is done,
 * so the tour quotes those words instead of inventing its own.
 */
export const TUTORIAL_STEPS = Object.freeze([
  step('workspace', TUTORIAL_EVENTS.WORKSPACE_CHOSEN, 'stepbar.line.noCase'),
  step('demo-case', TUTORIAL_EVENTS.CASE_CREATED, 'stepbar.line.saved'),
  step('validate', TUTORIAL_EVENTS.VALIDATION_DONE, 'stepbar.line.checked'),
  step('validation-result', TUTORIAL_EVENTS.VALIDATION_READ, 'stepbar.line.checked'),
  step('run', TUTORIAL_EVENTS.RUN_STARTED, 'stepbar.line.running'),
  step('run-progress', TUTORIAL_EVENTS.RUN_FINISHED, 'stepbar.line.ran'),
  step('result-graph', TUTORIAL_EVENTS.RESULTS_OPENED, 'stepbar.line.resultOpen'),
]);

/** "Start with my pipe table": steps 2 and 7 differ, the events are the same. */
const PIPE_STEPS = Object.freeze([
  TUTORIAL_STEPS[0],
  step('pipe-case', TUTORIAL_EVENTS.CASE_CREATED, 'stepbar.line.saved'),
  TUTORIAL_STEPS[2],
  TUTORIAL_STEPS[3],
  TUTORIAL_STEPS[4],
  TUTORIAL_STEPS[5],
  step('result-flow', TUTORIAL_EVENTS.RESULTS_OPENED, 'stepbar.line.resultOpen'),
]);

export const TUTORIAL_PATHS = Object.freeze(['demo', 'pipe']);

export function tutorialSteps(path) {
  return path === 'pipe' ? PIPE_STEPS : TUTORIAL_STEPS;
}

export const TOUR_FALLBACK_SELECTORS = Object.freeze({
  'result-graph': '[data-view="results"]',
  'result-flow': '[data-view="results"]',
});

export function tourTargetSelectors(target) {
  const primary = `[data-tour="${target}"]`;
  const fallback = TOUR_FALLBACK_SELECTORS[target];
  return fallback === undefined ? [primary] : [primary, fallback];
}

export function resolveTourTarget(target, query, usable = () => true) {
  const [primary, ...fallbacks] = tourTargetSelectors(target);
  const direct = query(primary);
  if (direct && usable(direct)) return direct;
  for (const selector of fallbacks) {
    const element = query(selector);
    const anchor = element ? (element.closest?.('button') ?? element) : null;
    if (anchor && usable(anchor)) return anchor;
  }
  return null;
}

export function resumeChipPending(state, acknowledged) {
  return state.status === 'active' && !acknowledged;
}

export function initialTutorialState() {
  return { version: 1, status: 'idle', index: 0, finishedWithoutOlga: false, path: 'demo' };
}

function isStateRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizeTutorialState(raw) {
  if (!isStateRecord(raw) || raw.version !== 1) return initialTutorialState();
  const status = raw.status;
  if (status !== 'idle' && status !== 'active' && status !== 'paused' && status !== 'skipped' && status !== 'done') {
    return initialTutorialState();
  }
  const index = raw.index;
  if (!Number.isInteger(index) || index < 0 || index > TUTORIAL_STEPS.length) return initialTutorialState();
  return {
    version: 1,
    status,
    index: status === 'done' || status === 'skipped' ? TUTORIAL_STEPS.length : index,
    finishedWithoutOlga: raw.finishedWithoutOlga === true,
    path: raw.path === 'pipe' ? 'pipe' : 'demo',
  };
}

export function startTutorial(state) {
  const current = normalizeTutorialState(state);
  if (current.status === 'done' || current.status === 'skipped') return current;
  return { ...current, status: 'active', index: Math.min(current.index, TUTORIAL_STEPS.length - 1) };
}

export function pauseTutorial(state) {
  const current = normalizeTutorialState(state);
  if (current.status !== 'active') return current;
  return { ...current, status: 'paused' };
}

export function resumeTutorial(state) {
  const current = normalizeTutorialState(state);
  if (current.status !== 'paused') return current;
  return { ...current, status: 'active' };
}

export function skipTutorial(state) {
  const current = normalizeTutorialState(state);
  if (current.status === 'done' || current.status === 'skipped') return current;
  return { ...current, status: 'skipped', index: TUTORIAL_STEPS.length };
}

export function resetTutorial(state) {
  const { path } = normalizeTutorialState(state);
  return { ...initialTutorialState(), status: 'active', path };
}

/** The path can change until the case step is done; after that the case belongs to one path. */
export function setTutorialPath(state, path) {
  const current = normalizeTutorialState(state);
  if (path !== 'demo' && path !== 'pipe') return current;
  if (current.status === 'done' || current.status === 'skipped') return current;
  if (current.index > 1) return current;
  return { ...current, path };
}

export function advanceTutorial(state, event) {
  const current = normalizeTutorialState(state);
  if (current.status !== 'active') return current;
  const steps = tutorialSteps(current.path);
  if (event === TUTORIAL_EVENTS.NO_OLGA) {
    if (steps[current.index]?.id !== NO_OLGA_STEP_ID) return current;
    return { ...current, status: 'done', index: TUTORIAL_STEPS.length, finishedWithoutOlga: true };
  }
  if (steps[current.index]?.event !== event) return current;
  const next = current.index + 1;
  if (next >= TUTORIAL_STEPS.length) {
    return { ...current, status: 'done', index: TUTORIAL_STEPS.length };
  }
  return { ...current, index: next };
}

export function isTutorialFinished(state) {
  const current = normalizeTutorialState(state);
  return current.status === 'done' || current.status === 'skipped';
}

function browserStorage() {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function loadTutorialState(storage = browserStorage()) {
  try {
    const raw = storage?.getItem(TUTORIAL_STORAGE_KEY);
    if (raw === null || raw === undefined) return initialTutorialState();
    return normalizeTutorialState(JSON.parse(raw));
  } catch {
    return initialTutorialState();
  }
}

export function saveTutorialState(state, storage = browserStorage()) {
  try {
    storage?.setItem(TUTORIAL_STORAGE_KEY, JSON.stringify(normalizeTutorialState(state)));
    return storage !== undefined;
  } catch {
    return false;
  }
}

export function requestTutorialOpen() {
  try {
    window.dispatchEvent(new CustomEvent(TUTORIAL_OPEN_EVENT));
  } catch {
    return;
  }
}

export function notifyTutorialChanged() {
  try {
    window.dispatchEvent(new CustomEvent(TUTORIAL_CHANGE_EVENT));
  } catch {
    return;
  }
}

/** One forward action per step. Completion stays in tutorialStepSatisfied. */
export function stepAction(stepId) {
  switch (stepId) {
    case 'workspace': return { kind: 'focus-workspace', labelKey: 'tutorial.action.workspace' };
    case 'demo-case': return { kind: 'install-demo', labelKey: 'tutorial.action.installDemo' };
    case 'pipe-case': return { kind: 'open-pipe-wizard', labelKey: 'tutorial.action.openPipeWizard' };
    case 'validate': return { kind: 'validate', labelKey: 'tutorial.action.validate' };
    case 'validation-result': return { kind: 'show-problems', labelKey: 'tutorial.action.readValidation' };
    case 'run': return { kind: 'open-run', labelKey: 'tutorial.action.run' };
    case 'run-progress': return { kind: 'open-run', labelKey: 'tutorial.action.watchRun' };
    case 'result-graph': return { kind: 'open-results', labelKey: 'tutorial.action.openResults' };
    case 'result-flow': return { kind: 'open-results', labelKey: 'tutorial.action.openFlow' };
    default: return null;
  }
}

/**
 * A step is done only for the tour case: the installed demo case, or on the
 * pipe path the case the wizard saved (the host passes it as installedCaseName).
 * A workspace that is already chosen still counts: the copy says so.
 * Validation, runs and results do not count for a different case, and a
 * run that was already in the timeline before this step does not count.
 */
export function tutorialStepSatisfied(stepId, facts) {
  const installed = typeof facts.installedCaseName === 'string' && facts.installedCaseName
    ? facts.installedCaseName
    : '';
  const activeMatches = installed !== '' && facts.activeCaseName === installed;
  switch (stepId) {
    case 'workspace':
      return Boolean(facts.workspaceRoot);
    case 'demo-case':
    case 'pipe-case':
      return activeMatches;
    case 'validate':
      return activeMatches && facts.validatedCaseName === installed && facts.validationOk === true;
    case 'validation-result':
      return facts.validatedCaseName === installed && facts.validationOk === true && facts.validationRead === true;
    case 'run':
      return activeMatches && facts.runStartedForCase === true;
    case 'run-progress':
      return activeMatches && facts.runFinishedForCase === true;
    case 'result-graph':
    case 'result-flow':
      return activeMatches && facts.resultsOpenedForCase === true;
    default:
      return false;
  }
}

export function freshRunIds(ids, baseline) {
  const fresh = [];
  for (const id of ids) {
    if (!baseline.has(id)) fresh.push(id);
  }
  return fresh;
}
