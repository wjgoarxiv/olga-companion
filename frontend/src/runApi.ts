import { normalizeRunStatus } from './lineageNormalization';
import { publishTaskbarObservation } from './taskbarRunFeed.mjs';
import type { OlgaDetection, RunPreview, RunStatus } from './runContracts';
import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

export async function runDetect(source?: string): Promise<OlgaDetection> {
  const query = source ? `?${new URLSearchParams({ source })}` : '';
  return (await jsonOrThrow(await apiFetch(`/api/run/detect${query}`))) as OlgaDetection;
}

/** Build the exact run command (no execution) for human review. */
export async function runPreview(source: string, candidateId: string, timeoutS = 3600): Promise<RunPreview> {
  return (await jsonOrThrow(
    await apiFetch('/api/run/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, timeout_s: timeoutS, candidate_id: candidateId }),
    }),
  )) as RunPreview;
}

// Run status does not name the case, so remember which case each run was started for.
const runSources = new Map<string, string>();

/** Execute a run after the human reviews and accepts the preview. */
export async function runExecute(source: string, candidateId: string, selectionId: string, timeoutS = 3600): Promise<{ run_id: string }> {
  const started = (await jsonOrThrow(
    await apiFetch('/api/run/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, candidate_id: candidateId, selection_id: selectionId, approved: true, timeout_s: timeoutS }),
    }),
  )) as { run_id: string };
  if (typeof started.run_id === 'string' && started.run_id) runSources.set(started.run_id, source);
  return started;
}

export async function fetchRunHistory(source: string, limit = 20): Promise<RunStatus[]> {
  const query = new URLSearchParams({ source, limit: String(limit) });
  const body = (await jsonOrThrow(await apiFetch(`/api/run/history?${query}`))) as {
    runs: RunStatus[];
  };
  return body.runs.map(normalizeRunStatus);
}

export async function runStatus(runId: string): Promise<RunStatus> {
  const status = (await jsonOrThrow(
    await apiFetch(`/api/run/status/${encodeURIComponent(runId)}`),
  )) as RunStatus;
  const source = runSources.get(runId);
  const normalized = source === undefined ? normalizeRunStatus(status) : { ...normalizeRunStatus(status), source };
  // Every existing poller already calls this. The taskbar listens here so it
  // does not issue a second status request for the same run.
  publishTaskbarObservation({ kind: 'run', status: normalized });
  return normalized;
}

/** Cancel a run — this route terminates the supervised OLGA process. */
export async function runCancel(runId: string): Promise<RunStatus> {
  const status = (await jsonOrThrow(
    await apiFetch(`/api/run/cancel/${encodeURIComponent(runId)}`, {
      method: 'POST',
    }),
  )) as RunStatus;
  return normalizeRunStatus(status);
}
