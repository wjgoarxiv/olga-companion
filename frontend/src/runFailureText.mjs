// Run-failure words in the UI language, chosen by the failure code the server sends. A code
// not listed here keeps the server's own words, so nothing is ever shown blank or guessed.

const STEPS = {
  run_cancelled: 1,
  run_timed_out: 1,
  run_helper_failed: 3,
  opi_engine_start_failed: 1,
  olga_dll_load_failed: 3,
  native_communication_failure: 3,
  native_process_failed: 1,
  process_start_failed: 1,
  run_interrupted: 1,
};
// The operating system's own reason, shown as is: the whole detail of a start failure, the
// part after "Reason: " of a helper failure (the paragraph before it is already translated).
function serverReason(failure) {
  if (typeof failure.detail !== 'string') return null;
  if (failure.code === 'process_start_failed') return failure.detail.trim() || null;
  if (failure.code !== 'run_helper_failed') return null;
  const at = failure.detail.lastIndexOf('Reason: ');
  return at < 0 ? null : failure.detail.slice(at + 'Reason: '.length).trim() || null;
}

/** i18n keys for the title, detail and steps of a known failure code; null for an unknown one. */
export function runFailureView(failure, exitCode) {
  if (!failure || typeof failure.code !== 'string' || !Object.hasOwn(STEPS, failure.code)) return null;
  const variant = failure.code === 'run_interrupted' && failure.variant === 'helper_gone' ? '.helper_gone' : '';
  const base = `run.failure.${failure.code}${variant}`;
  return {
    titleKey: `${base}.title`,
    detailKey: `${base}.detail`,
    stepKeys: Array.from({ length: STEPS[failure.code] }, (_, index) => `${base}.step${index + 1}`),
    params: { exit: exitCode == null ? '' : String(exitCode) },
    serverReason: serverReason(failure),
  };
}
