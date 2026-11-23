// What the run strip under the top bar shows for one run observation from the app-wide feed.

export const STRIP_LINGER_MS = 20_000;
const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'timed_out']);
// Below this share of the run, a time-left guess swings too much to be worth showing.
const ETA_MIN_FRACTION = 0.02;

const HIDDEN = Object.freeze({ visible: false });

export function runStripModel(observation, { now, terminalSince }) {
  if (!observation || observation.kind !== 'run' || !observation.status) return HIDDEN;
  const status = observation.status;
  const progress = status.solver_progress ?? {};
  const terminal = TERMINAL.has(status.state);
  if (terminal && (terminalSince == null || now - terminalSince > STRIP_LINGER_MS)) return HIDDEN;

  let tone = 'running';
  if (terminal) tone = status.state === 'completed' ? 'completed' : 'failed';
  else if (status.cancel_requested) tone = 'stopping';
  else if (status.state === 'supervision_unknown') tone = 'unknown';
  else if (status.state === 'finalizing') tone = 'finalizing';

  const fraction = typeof progress.fraction === 'number' && Number.isFinite(progress.fraction)
    ? Math.min(1, Math.max(0, progress.fraction))
    : null;
  const percent = terminal && status.state === 'completed' ? 100 : fraction == null ? null : Math.floor(fraction * 100);
  const elapsedS = Number.isFinite(status.elapsed_ms) ? status.elapsed_ms / 1000 : null;
  const etaS = tone === 'running' && fraction != null && fraction >= ETA_MIN_FRACTION && fraction < 1 && elapsedS != null
    ? Math.round(elapsedS * (1 - fraction) / fraction)
    : null;

  return {
    visible: true,
    runId: status.run_id,
    caseName: status.source_name ?? '',
    tone,
    percent,
    simTimeS: typeof progress.simulation_time_s === 'number' ? progress.simulation_time_s : null,
    elapsedS,
    etaS,
    canStop: !terminal && !status.cancel_requested,
    canOpenResults: status.state === 'completed',
  };
}

/** Whole hours, minutes and seconds for the strip's time words. */
export function durationParts(seconds) {
  const total = Math.max(0, Math.round(seconds));
  return { h: Math.floor(total / 3600), m: Math.floor((total % 3600) / 60), s: total % 60, total };
}
