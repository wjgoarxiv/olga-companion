// Plain words for why a run stopped, built only from the parsed OLGA stop message (run_stop_reason.py).

const TABLE_CODES = new Set(['pressure_above_table', 'pressure_below_table', 'temperature_above_table', 'temperature_below_table']);

function shown(value, digits) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '';
  return digits == null ? String(value) : String(Number(value.toFixed(digits)));
}

/** Where to look in the case, as an i18n key with its values; null when OLGA named no clear place. */
export function stopPointerView(pointer) {
  if (!pointer || typeof pointer !== 'object') return null;
  const text = (value) => (typeof value === 'string' ? value : '');
  if (pointer.kind === 'node' && text(pointer.label)) return { key: 'run.stop.pointer.node', params: { label: pointer.label } };
  if (pointer.kind === 'pipe' && text(pointer.label) && Number.isInteger(pointer.section)) {
    return { key: 'run.stop.pointer.pipe', params: { label: pointer.label, flowpath: text(pointer.flowpath), section: String(pointer.section) } };
  }
  if (pointer.kind === 'keyword' && text(pointer.keyword) && text(pointer.key)) {
    return { key: 'run.stop.pointer.keyword', params: { component: text(pointer.component), keyword: pointer.keyword, key: pointer.key } };
  }
  return null;
}

/** Title, detail and steps as i18n keys with their values; null when the run has no stop reason. */
export function stopReasonView(reason) {
  if (!reason || typeof reason !== 'object') return null;
  const params = {
    time: shown(reason.stopped_at_s, 1),
    where: typeof reason.where === 'string' ? reason.where : '',
    p: shown(reason.pressure_bara),
    t: shown(reason.temperature_c),
  };
  const evidence = typeof reason.evidence === 'string' && reason.evidence ? reason.evidence : null;
  const pointer = stopPointerView(reason.pointer);
  const lastLines = Array.isArray(reason.last_lines) ? reason.last_lines.filter((line) => typeof line === 'string') : [];
  if (TABLE_CODES.has(reason.code)) {
    const pressure = reason.code.startsWith('pressure');
    return {
      known: true,
      titleKey: `run.stop.title.${reason.code}`,
      detailKey: 'run.stop.detail.table',
      params,
      stepKeys: [pressure ? 'run.stop.step.widerTablePressure' : 'run.stop.step.widerTableTemperature', 'run.stop.step.checkBoundary', 'run.stop.step.ask'],
      lastLines,
      evidence,
      pointer,
    };
  }
  if (reason.code === 'input_rejected') {
    return {
      known: true,
      titleKey: 'run.stop.title.input_rejected',
      detailKey: 'run.stop.detail.input_rejected',
      params,
      stepKeys: ['run.stop.step.fixInput', 'run.stop.step.ask'],
      lastLines,
      evidence,
      pointer,
    };
  }
  return {
    known: false,
    titleKey: 'run.stop.title.unknown',
    detailKey: 'run.stop.detail.unknown',
    params: { ...params, code: reason.exit_code == null ? '' : String(reason.exit_code), message: typeof reason.exit_message === 'string' ? reason.exit_message : '' },
    stepKeys: ['run.stop.step.readLines', 'run.stop.step.ask'],
    lastLines,
    evidence,
    pointer: null,
  };
}

/** The facts for the assistant: the parsed stop message and OLGA's last lines, with no file paths. */
export function stopReasonPrompt(reason, caseName) {
  const lines = Array.isArray(reason?.last_lines) ? reason.last_lines : [];
  const facts = [
    `case: ${caseName ?? ''}`,
    `stop code: ${reason?.code ?? 'unknown'}`,
    reason?.stopped_at_s != null ? `stopped at: ${shown(reason.stopped_at_s, 1)} s` : '',
    reason?.where ? `reported in: ${reason.where}` : '',
    reason?.evidence ? `OLGA line: ${reason.evidence}` : '',
    reason?.pressure_bara != null ? `pressure: ${shown(reason.pressure_bara)} bara` : '',
    reason?.temperature_c != null ? `temperature: ${shown(reason.temperature_c)} C` : '',
    reason?.exit_code != null ? `exit: ${reason.exit_code}${reason.exit_message ? ` (${reason.exit_message})` : ''}` : '',
  ].filter(Boolean);
  const body = [...facts, 'OLGA last lines:', ...lines].join('\n').replace(/[A-Za-z]:\\[^\s]*/g, '[path]').replace(/\/Users\/[^\s]*/g, '[path]');
  return body;
}
