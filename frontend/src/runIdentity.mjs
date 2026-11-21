import { cellField, displayUnit, displayValue } from './caseEditModel.mjs';

// A run of an approved edit copy is named by the change that was approved for it (the server links
// the two only by the hash of the case the run used). A hand-made case has no approved_change.

const SHOWN = 3;
const RUN_COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)', 'var(--s5)'];

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

// The group names case_transaction_apply.py ends a grouped path with; any other last part is the item.
const GROUP_NAMES = new Set(['values', 'time_step', 'geometry']);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** One change per field: a grouped change ({a: 1, b: 2} → {a: 3, b: 2}) is split by the fields it
 *  changed; a field written again with its old value is not a change. A grouped path ends in its group
 *  name ("controllers.PC.values") or in the item itself ("massflow_sources.SRC"). */
function flatten(change) {
  const parts = change.path.split('.');
  if (isRecord(change.before) && isRecord(change.after)) {
    const target = parts.slice(1, GROUP_NAMES.has(parts[parts.length - 1]) ? -1 : undefined).join('.');
    return Object.keys(change.after)
      .filter((field) => !same(change.before[field], change.after[field]))
      .map((field) => ({ target, field, before: change.before[field], after: change.after[field], unit: field === 'setpoint' ? change.unit : undefined }));
  }
  const target = parts.slice(1, -1).join('.');
  return [{ target, field: parts[parts.length - 1], before: change.before, after: change.after, unit: change.unit }];
}

/** The value as the edit table shows it, or null for a value that is not one number. */
function shown(value, item) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return String(displayValue({ field: item.field, unit: item.unit, value }));
}

function fieldName(field, t) {
  const key = `caseEdit.field.${field}`;
  const label = t(key);
  return label === key ? field : label.replace(/\s*\([^)]*\)\s*$/, '');
}

/** "PC PID 설정값 20→25 bar" for each approved change, at most three and "+N" for the rest; null without one. */
export function changeLabel(file, t) {
  const changes = file?.approved_change?.changes;
  if (!Array.isArray(changes) || changes.length === 0) return null;
  const items = changes.flatMap(flatten).map((item) => {
    const before = shown(item.before, item);
    const after = shown(item.after, item);
    const unit = displayUnit(cellField(item));
    const name = [item.target, fieldName(item.field, t)].filter(Boolean).join(' ');
    return before !== null && after !== null ? `${name} ${before}→${after}${unit ? ` ${unit}` : ''}` : name;
  });
  const head = items.slice(0, SHOWN).join(', ');
  return items.length > SHOWN ? `${head} ${t('runLabel.more', { count: items.length - SHOWN })}` : head;
}

/** The same colour for the same run on every surface: hashed from the run part of the result id
 *  (`run:<id>/case.tpl` and `run:<id>/case.ppl` are one run). */
export function runColor(id) {
  const text = String(id);
  const run = text.startsWith('run:') ? text.split('/')[0] : text;
  let hash = 0x811c9dc5;
  for (const char of run) hash = Math.imul(hash ^ char.codePointAt(0), 0x01000193) >>> 0;
  return RUN_COLORS[hash % RUN_COLORS.length];
}
