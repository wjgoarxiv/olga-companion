import { normalizeRunStatus } from './lineageNormalization';
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

/** Execute a run after the human reviews and accepts the preview. */
export async function runExecute(source: string, candidateId: string, selectionId: string, timeoutS = 3600): Promise<{ run_id: string }> {
  return (await jsonOrThrow(
    await apiFetch('/api/run/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, candidate_id: candidateId, selection_id: selectionId, approved: true, timeout_s: timeoutS }),
    }),
  )) as { run_id: string };
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
  return normalizeRunStatus(status);
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
