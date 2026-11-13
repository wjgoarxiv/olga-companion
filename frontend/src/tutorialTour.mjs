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

export const TUTORIAL_STEPS = Object.freeze([
  Object.freeze({ id: 'workspace', target: 'workspace', textKey: 'tutorial.step.workspace', event: TUTORIAL_EVENTS.WORKSPACE_CHOSEN }),
  Object.freeze({ id: 'demo-case', target: 'demo-case', textKey: 'tutorial.step.demo-case', event: TUTORIAL_EVENTS.CASE_CREATED }),
  Object.freeze({ id: 'validate', target: 'validate', textKey: 'tutorial.step.validate', event: TUTORIAL_EVENTS.VALIDATION_DONE }),
  Object.freeze({ id: 'validation-result', target: 'validation-result', textKey: 'tutorial.step.validation-result', event: TUTORIAL_EVENTS.VALIDATION_READ }),
  Object.freeze({ id: 'run', target: 'run', textKey: 'tutorial.step.run', event: TUTORIAL_EVENTS.RUN_STARTED }),
  Object.freeze({ id: 'run-progress', target: 'run-progress', textKey: 'tutorial.step.run-progress', event: TUTORIAL_EVENTS.RUN_FINISHED }),
  Object.freeze({ id: 'result-graph', target: 'result-graph', textKey: 'tutorial.step.result-graph', event: TUTORIAL_EVENTS.RESULTS_OPENED }),
]);

export const TOUR_FALLBACK_SELECTORS = Object.freeze({
  'result-graph': '[data-view="results"]',
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
  return { version: 1, status: 'idle', index: 0, finishedWithoutOlga: false };
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
  void state;
  return { ...initialTutorialState(), status: 'active' };
}

export function advanceTutorial(state, event) {
  const current = normalizeTutorialState(state);
  if (current.status !== 'active') return current;
  if (event === TUTORIAL_EVENTS.NO_OLGA) {
    if (TUTORIAL_STEPS[current.index]?.id !== NO_OLGA_STEP_ID) return current;
    return { ...current, status: 'done', index: TUTORIAL_STEPS.length, finishedWithoutOlga: true };
  }
  if (TUTORIAL_STEPS[current.index]?.event !== event) return current;
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
