/** The stop card's "Open in edit table": ask the server which row the stop names, then open the
    table at that row. Only a GET is made; the user types the value and saves through the table's
    own review and Approve click. */

export const REMEDY_REASONS = Object.freeze([
  'table_range', 'unknown', 'sweep_only', 'fixed', 'not_editable', 'ambiguous', 'source_changed', 'outside_workspace',
]);

export async function openStopRemedy(runId, { get, activeCase, open }) {
  const remedy = await get(`/api/case-edit/remedy?run_id=${encodeURIComponent(runId)}`);
  if (!remedy || typeof remedy.row_id !== 'string' || typeof remedy.rel !== 'string') {
    const reason = REMEDY_REASONS.includes(remedy?.reason_key) ? remedy.reason_key : 'unknown';
    return { reasonKey: `run.stop.remedy.reason.${reason}` };
  }
  // No open case (null) means the table cannot open there either; say so rather than do nothing.
  if (activeCase !== undefined && remedy.rel.split('/').pop() !== activeCase) {
    return { reasonKey: 'run.stop.remedy.reason.not_active' };
  }
  open(remedy.rel, remedy.row_id);
  return { reasonKey: null };
}
