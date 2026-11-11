import { runStatusIsPollable, sweepStatusIsPollable } from './runPolling';
import { splitSweepValues } from './sweepValueGrammar';
import type { I18nKey } from './i18n/ko.ts';
import type { RunViewState } from './useRunViewState';

export type RunText = (key: I18nKey, vars?: Record<string, string | number>) => string;

export function launcherKindLabel(kind: string | null, t?: RunText | null): string {
  if (kind === 'opi') return t?.('run.launcher.opi') ?? 'OPI launcher';
  if (kind === 'engine') return t?.('run.launcher.engine') ?? 'direct engine';
  if (kind === 'script') return t?.('run.launcher.script') ?? 'script launcher';
  return kind || (t?.('run.launcher.unknown') ?? 'launcher unknown');
}

export function deriveRunViewModel(state: RunViewState, t?: RunText | null) {
  const {
    active, activeLoaded, contextUnavailable, detect, selectedCandidateId,
    status, sweepStatus, supervisionUnknown, sweepSupervisionUnknown,
    contextLoading, preview, previewing, starting, cancelling,
    sweepParameter, sweepValues, sweepPreviewing, sweepStarting, sweepCancelling,
  } = state;
  const text = (key: I18nKey, vars?: Record<string, string | number>): string | null =>
    t ? t(key, vars) : null;
  const caseLabel = contextUnavailable
    ? text('run.titleMissing') ?? '실행 정보 없음'
    : !activeLoaded
      ? text('run.titleLoading') ?? 'Loading active case…'
      : active?.name || (text('run.noActiveCase') ?? 'No active case');
  const activeIsGenkey = active?.path?.toLowerCase().endsWith('.genkey') === true;
  const selectionBlocked = detect != null && (!detect.detected || detect.selection_status === 'missing_required_version');
  const runtimeCandidates = (detect?.candidates ?? []).filter((candidate) =>
    candidate.version === detect?.version && (candidate.kind === 'opi' || candidate.kind === 'engine')
  );
  const selectedCandidate = runtimeCandidates.find((candidate) => candidate.candidate_id === selectedCandidateId) ?? null;
  const runReady = !contextUnavailable && activeIsGenkey && detect?.detected === true && !selectionBlocked && selectedCandidate != null;
  const engineLabel = contextUnavailable
    ? text('run.engineRetry') ?? 'Retry required'
    : !activeLoaded
      ? text('run.engineWaiting') ?? 'Waiting for active case'
      : !active?.path
        ? text('run.engineCaseRequired') ?? 'Case required'
        : !activeIsGenkey
          ? text('run.engineGenkeyRequired') ?? 'GENKEY case required'
          : detect == null
            ? text('run.engineChecking') ?? 'Checking compatibility…'
            : runReady
              ? `OLGA ${detect.version || (text('run.versionUnknown') ?? 'version unknown')} · ${launcherKindLabel(detect.kind, t)}`
              : selectionBlocked
                ? text('run.engineRequiredVersion', { version: detect.required_version || 'required version' }) ?? `OLGA ${detect.required_version || 'required version'} required`
                : text('run.engineNotDetected') ?? 'Not detected';
  const runPollable = status != null && runStatusIsPollable(status);
  const sweepPollable = sweepStatus != null && sweepStatusIsPollable(sweepStatus);
  const runCancellable = runPollable && status?.state !== 'finalizing';
  const sweepCancellable = sweepPollable && sweepStatus?.state !== 'finalizing';
  const monitoringUnknown = supervisionUnknown || sweepSupervisionUnknown;
  const requestOperationActive = contextLoading || previewing || starting || cancelling || sweepPreviewing || sweepStarting || sweepCancelling;
  const safetyOperationActive = requestOperationActive || runPollable || sweepPollable;
  const activeOperation = contextLoading
    ? text('run.opReloading') ?? 'Reloading run context…'
    : previewing
      ? text('run.opPreparing') ?? 'Preparing command…'
      : starting
        ? text('run.opStarting') ?? 'Starting OLGA…'
        : cancelling
          ? text('run.opCancelling') ?? 'Cancelling run…'
          : sweepPreviewing
            ? text('run.opSweepPreview') ?? 'Preparing sweep…'
            : sweepStarting
              ? text('run.opSweepStarting') ?? 'Starting sweep…'
              : sweepCancelling
                ? text('run.opSweepCancelling') ?? 'Cancelling sweep…'
                : '';
  const sweepSpec = sweepParameter.trim() && sweepValues.trim()
    ? `${sweepParameter.trim()}=${sweepValues.trim()}`
    : '';
  const sweepCaseCount = splitSweepValues(sweepValues).length;

  // The preview receipt names the launcher exactly once; panels read this
  // instead of formatting the launcher themselves.
  const previewLauncherText = preview
    ? `OLGA ${preview.detection.version || (text('run.versionUnknown') ?? 'version unknown')} · ${launcherKindLabel(preview.detection.kind, t)}`
    : null;
  return {
    caseLabel, activeIsGenkey, selectionBlocked, runtimeCandidates, runReady,
    engineLabel, runCancellable, sweepCancellable,
    monitoringUnknown, requestOperationActive, safetyOperationActive,
    activeOperation, sweepSpec, sweepCaseCount, previewLauncherText,
  };
}

export type RunViewModel = ReturnType<typeof deriveRunViewModel>;
