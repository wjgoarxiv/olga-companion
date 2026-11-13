function basename(value) {
  if (typeof value !== 'string' || value === '') return '';
  const parts = value.split(/[/\\]/);
  return parts[parts.length - 1] ?? '';
}

function caseNames(status) {
  const names = new Set();
  for (const field of ['source_name', 'source', 'staged_case_name']) {
    const name = basename(status?.[field]);
    if (name) names.add(name);
  }
  if (Array.isArray(status?.command)) {
    for (const part of status.command) {
      const name = basename(part);
      if (name) names.add(name);
    }
  }
  return names;
}

/** A Run-view status counts only when it is the installed demo case. */
export function demoRunSignal(observation, installedCaseName) {
  if (!observation || observation.kind !== 'run' || !installedCaseName) return null;
  const status = observation.status;
  if (!status || typeof status !== 'object') return null;
  const runId = typeof status.run_id === 'string' ? status.run_id : '';
  if (!runId || !caseNames(status).has(installedCaseName)) return null;
  return { runId, started: true, finished: status.state === 'completed' };
}
