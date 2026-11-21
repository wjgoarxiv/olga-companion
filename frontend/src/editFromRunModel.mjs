const REASONS = new Set(['changed', 'missing', 'outside_workspace', 'unrecorded', 'same_name']);

/** Workspace paths compare with one separator: Windows lists a subfolder case with `\`. */
const samePath = (a, b) => typeof a === 'string' && typeof b === 'string' && a.replaceAll('\\', '/') === b.replaceAll('\\', '/');

/** Make the run's case active when it is not, then ask the workspace to open its table. A switch
 *  that failed sends nothing, so no request is left waiting to open later by surprise. */
export async function openFromRun(rel, { activeName, pickCase, openWorkspace, request }) {
  if (rel.split(/[\\/]/).pop() !== activeName && (await pickCase(rel)) === false) return false;
  openWorkspace();
  request(rel);
  return true;
}

/** What a result header offers: the case to open, the reason it cannot, or nothing for a file
 *  that is not a run result. */
export function editFromRun(result) {
  const source = result?.edit_source;
  if (!source) return null;
  if (typeof source.rel === 'string' && source.rel) return { kind: 'open', rel: source.rel };
  const reason = REASONS.has(source.reason) ? source.reason : 'unknown';
  return { kind: 'reason', key: `results.editFromRun.reason.${reason}` };
}

/** Whether a staged edit request opens now, waits for its case to become the one shown, or is
 *  dropped because another case became active instead. */
export function editTargetStep({ target, selected, activeRel, activeAtRequest }) {
  if (!target || samePath(target.rel, selected)) return 'open';
  if (samePath(target.rel, activeRel) || activeRel === activeAtRequest) return 'wait';
  return 'drop';
}
