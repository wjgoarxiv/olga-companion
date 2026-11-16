// Presentational mapping from the UpdatePanel phase to the six-stage track:
// checking -> available -> downloading -> verifying -> installing -> restarting.
// No flow logic lives here: checking, downloading, installing and relaunching
// still go through updateInstall.mjs, updateAutoCheck.mjs and
// useLaunchUpdateCheck.ts exactly as before. The `error` phase carries the
// stage that was running when it failed (set at the call site); `blocked` is
// always the install step refusing, so it marks installing as blocked.

export const UPDATE_STAGES = ['checking', 'available', 'downloading', 'verifying', 'installing', 'restarting'];

// A downloaded (or install-refused) package lives only in the Update handle, so a re-check in
// those phases must not clear or close it.
export function keepsUpdateHandle(phase) {
  return phase?.kind === 'downloaded' || phase?.kind === 'blocked';
}

function freshStates() {
  return Object.fromEntries(UPDATE_STAGES.map((id) => [id, 'todo']));
}

export function stageOfPhase(phase) {
  const states = freshStates();
  const doneThrough = (id) => {
    for (const stage of UPDATE_STAGES) {
      states[stage] = 'done';
      if (stage === id) break;
    }
  };
  switch (phase?.kind) {
    case 'checking':
      states.checking = 'active';
      return { states, active: 'checking', failed: null, blocked: null };
    case 'current':
      states.checking = 'done';
      return { states, active: null, failed: null, blocked: null };
    case 'available':
      doneThrough('checking');
      states.available = 'active';
      return { states, active: 'available', failed: null, blocked: null };
    case 'downloading':
      doneThrough('available');
      states.downloading = 'active';
      return { states, active: 'downloading', failed: null, blocked: null };
    case 'downloaded':
      // The updater verifies the signature as part of the download, so a
      // downloaded package has passed verifying; the track waits for install.
      doneThrough('verifying');
      return { states, active: null, failed: null, blocked: null };
    case 'installing':
      doneThrough('verifying');
      states.installing = 'active';
      return { states, active: 'installing', failed: null, blocked: null };
    case 'blocked':
      doneThrough('verifying');
      states.installing = 'blocked';
      return { states, active: null, failed: null, blocked: 'installing' };
    case 'error': {
      const at = UPDATE_STAGES.includes(phase.stage)
        ? phase.stage
        : (phase.backendStopped ? 'installing' : 'checking');
      for (const stage of UPDATE_STAGES) {
        if (stage === at) break;
        states[stage] = 'done';
      }
      states[at] = 'failed';
      return { states, active: null, failed: at, blocked: null };
    }
    default:
      return { states, active: null, failed: null, blocked: null };
  }
}
