export const PLAN_ACTION = 'action_plan';

const STATES = new Set(['waiting', 'done', 'failed', 'uncertain', 'not_run']);
const RUN_KIND = 'run_execute';

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function stateByIndex(result) {
  const states = new Map();
  if (!isRecord(result) || !Array.isArray(result.steps)) return states;
  for (const step of result.steps) {
    if (isRecord(step) && typeof step.index === 'number' && STATES.has(step.state)) {
      states.set(step.index, { state: step.state, error: typeof step.error === 'string' ? step.error : '' });
    }
  }
  return states;
}

/** The reviewed input rows of one step, grouped in the order the server sent them. */
function groupInputs(raw) {
  const groups = [];
  for (const entry of Array.isArray(raw) ? raw : []) {
    if (!isRecord(entry) || typeof entry.group !== 'string' || typeof entry.name !== 'string' || typeof entry.value !== 'string') continue;
    let group = groups.find((candidate) => candidate.group === entry.group);
    if (!group) {
      group = { group: entry.group, items: [] };
      groups.push(group);
    }
    group.items.push({ name: entry.name, value: entry.value, unit: typeof entry.unit === 'string' ? entry.unit : '' });
  }
  return groups;
}

/** Pair the server's reviewed step rows with the per-step states of a plan result. */
export function planStepRows(display, result) {
  const steps = isRecord(display) && isRecord(display.plan) ? display.plan.steps : undefined;
  if (!Array.isArray(steps)) return [];
  const states = stateByIndex(result);
  return steps.flatMap((step) => {
    if (!isRecord(step) || typeof step.index !== 'number' || typeof step.kind !== 'string') return [];
    const fields = (Array.isArray(step.fields) ? step.fields : []).flatMap((field) => (
      isRecord(field) && typeof field.key === 'string' && typeof field.value === 'string'
        ? [{ key: field.key, value: field.value, unit: typeof field.unit === 'string' ? field.unit : '' }]
        : []
    ));
    const unknown = (Array.isArray(step.unknown) ? step.unknown : []).filter((key) => typeof key === 'string');
    const known = states.get(step.index);
    return [{
      index: step.index,
      kind: step.kind,
      fields,
      inputs: groupInputs(step.inputs),
      unknown,
      boundTo: typeof step.bound_to === 'number' ? step.bound_to : null,
      state: known?.state ?? 'waiting',
      error: known?.error ?? '',
    }];
  });
}

/** What happened to the whole sequence, or null while no result is known. */
export function planOutcome(result) {
  if (!isRecord(result) || !Array.isArray(result.steps)) return null;
  if (result.steps.length === 0) {
    // A plan closed before any step ran carries no rows but is still a failure.
    return result.ok === false || result.state === 'stopped' ? 'stopped' : null;
  }
  const steps = result.steps.map((step) => (isRecord(step) ? step : {}));
  if (steps.some((step) => step.state === 'uncertain')) return 'uncertain';
  if (!steps.every((step) => step.state === 'done')) return 'stopped';
  // A done run step only means the run started; it may still be running.
  return steps.some((step) => step.kind === RUN_KIND) ? 'started' : 'completed';
}

/** The lifecycle a plan settles in once the model has continued: a stopped plan never reads completed. */
export function planSettledState(result) {
  return planOutcome(result) === 'stopped' ? 'failed' : 'completed';
}

/** The sentence the server gave for why the whole sequence stopped, or ''. */
export function planError(result) {
  return isRecord(result) && typeof result.error === 'string' ? result.error : '';
}
