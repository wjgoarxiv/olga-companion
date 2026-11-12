import { runStatusIsPollable, sweepStatusIsPollable } from './runPolling';
import * as session from './session';
import { pushRunConsoleEntry, setRunConsoleSnapshot } from './runConsole';
import { playCue, trackRun } from './sound.mjs';
import { useLocale } from './i18n/index.ts';
import type { RunViewModel } from './runViewModel';
import type { RunLifecycle } from './useRunLifecycle';
import type { RunViewState } from './useRunViewState';

export function useRunActions(
  state: RunViewState,
  lifecycle: RunLifecycle,
  model: RunViewModel,
) {
  const {
    active, selectedCandidateId, timeoutHours, preview, runId, sweepPreview, sweepId,
    operationRequestRef, runExecuteLockRef, sweepExecuteLockRef,
    setDetect, setPreview, setUsedSelectionId, setPreviewing, setRunId, setStatus, setStatusSource,
    setSupervisionUnknown, setStarting, setCancelling,
    setSweepPreview, setSweepId, setSweepStatus,
    setSweepSupervisionUnknown, setSweepPreviewing,
    setSweepStarting, setSweepCancelling,
  } = state;
  const {
    clearError, err, operationIsCurrent, stopPolling,
    startRunPolling, startSweepPolling,
  } = lifecycle;
  const { activeIsGenkey, runReady, sweepSpec } = model;
  const { t } = useLocale();

  async function doPreview() {
    if (!active?.path || !activeIsGenkey || !runReady || !selectedCandidateId) return;
    const requestId = operationRequestRef.current.begin();
    if (!operationIsCurrent(requestId)) return;
    clearError();
    setPreviewing(true);
    setRunConsoleSnapshot({ starting: true });
    try {
      const next = await session.runPreview(active.path, selectedCandidateId, timeoutHours * 3600);
      if (!operationIsCurrent(requestId)) return;
      setPreview(next);
      setUsedSelectionId('');
      playCue(next.validation.valid ? 'pass' : 'fail');
      setDetect(next.detection);
      setRunConsoleSnapshot({ state: 'preview', starting: false });
      pushRunConsoleEntry('ok', t('run.consolePreviewReady'));
    } catch (e) {
      if (!operationIsCurrent(requestId)) return;
      if (e instanceof Error) { err(e); return; }
      throw e;
    } finally {
      if (!operationIsCurrent(requestId)) return;
      setPreviewing(false);
      setRunConsoleSnapshot({ starting: false });
    }
  }

  async function doRun() {
    if (!active?.path || !runReady || !preview?.selection_id || !preview.validation.valid) return;
    const lockId = runExecuteLockRef.current.begin();
    if (lockId == null) return;
    const requestId = operationRequestRef.current.begin();
    try {
      if (!operationIsCurrent(requestId)) return;
      clearError();
      stopPolling();
      setRunId(null);
      setStatus(null);
      setStatusSource('live');
      setSupervisionUnknown(false);
      setStarting(true);
      // Marked before the call: if the answer is lost the run may still have started.
      pushRunConsoleEntry('info', t('run.consoleRunStart'));
      setRunConsoleSnapshot({ state: 'starting', starting: true });
      setUsedSelectionId(preview.selection_id);
      const started = await session.runExecute(active.path, preview.candidate_id, preview.selection_id, preview.timeout_s);
      if (!operationIsCurrent(requestId)) return;
      setRunId(started.run_id);
      trackRun(started.run_id);
      setSupervisionUnknown(true);
      startRunPolling(started.run_id);
    } catch (e) {
      if (!operationIsCurrent(requestId)) return;
      if (e instanceof Error) { err(e); setStarting(false); pushRunConsoleEntry('fail', t('run.consoleRunFailed')); setRunConsoleSnapshot({ starting: false }); return; }
      throw e;
    } finally {
      runExecuteLockRef.current.end(lockId);
    }
  }

  async function doCancel() {
    if (!runId) return;
    const requestId = operationRequestRef.current.begin();
    if (!operationIsCurrent(requestId)) return;
    clearError();
    stopPolling();
    setSupervisionUnknown(true);
    setCancelling(true);
    pushRunConsoleEntry('info', t('run.consoleCancelRequested'));
    try {
      const cancelled = await session.runCancel(runId);
      if (!operationIsCurrent(requestId)) return;
      setStatus(cancelled);
      setSupervisionUnknown(cancelled.state === 'supervision_unknown');
      if (runStatusIsPollable(cancelled)) startRunPolling(runId);
    } catch (e) {
      if (!operationIsCurrent(requestId)) return;
      if (e instanceof Error) { setSupervisionUnknown(true); err(e, true); return; }
      throw e;
    } finally {
      if (!operationIsCurrent(requestId)) return;
      setCancelling(false);
    }
  }

  function resetSweepPlan() {
    stopPolling();
    setSweepPreview(null);
    setSweepId(null);
    setSweepStatus(null);
  }

  async function doSweepPreview() {
    if (!active?.path || !activeIsGenkey || !runReady || !sweepSpec.trim()) return;
    const requestId = operationRequestRef.current.begin();
    if (!operationIsCurrent(requestId)) return;
    clearError();
    setSweepPreviewing(true);
    setRunConsoleSnapshot({ starting: true });
    try {
      const planned = await session.sweepPreview(active.path, [sweepSpec.trim()]);
      if (!operationIsCurrent(requestId)) return;
      setSweepPreview(planned);
      setSweepId(planned.sweep_id);
      setSweepStatus(null);
      setRunConsoleSnapshot({ state: 'preview', starting: false });
      pushRunConsoleEntry('ok', t('run.consoleSweepPreviewReady'));
    } catch (e) {
      if (!operationIsCurrent(requestId)) return;
      if (e instanceof Error) { err(e); pushRunConsoleEntry('fail', t('run.consoleRunFailed')); return; }
      throw e;
    } finally {
      if (!operationIsCurrent(requestId)) return;
      setSweepPreviewing(false);
      setRunConsoleSnapshot({ starting: false });
    }
  }

  async function doSweepRun() {
    if (!sweepPreview) return;
    if (!active?.path || !activeIsGenkey || !runReady || !sweepSpec.trim()) return;
    const lockId = sweepExecuteLockRef.current.begin();
    if (lockId == null) return;
    const requestId = operationRequestRef.current.begin();
    try {
      if (!operationIsCurrent(requestId)) return;
      clearError();
      setSweepStarting(true);
      setSweepId(sweepPreview.sweep_id);
      pushRunConsoleEntry('info', t('run.consoleSweepStart'));
      setRunConsoleSnapshot({ state: 'starting', starting: true });
      const started = await session.sweepExecute(sweepPreview.sweep_id, sweepPreview.plan_id);
      if (!operationIsCurrent(requestId)) return;
      setSweepStatus(started);
      setSweepStarting(false);
      setSweepSupervisionUnknown(true);
      startSweepPolling(sweepPreview.sweep_id);
    } catch (e) {
      if (!operationIsCurrent(requestId)) return;
      if (e instanceof Error) { err(e); setSweepStarting(false); pushRunConsoleEntry('fail', t('run.consoleRunFailed')); setRunConsoleSnapshot({ starting: false }); return; }
      throw e;
    } finally {
      sweepExecuteLockRef.current.end(lockId);
    }
  }

  async function doSweepCancel() {
    if (!sweepId) return;
    const requestId = operationRequestRef.current.begin();
    if (!operationIsCurrent(requestId)) return;
    clearError();
    stopPolling();
    setSweepSupervisionUnknown(true);
    setSweepCancelling(true);
    pushRunConsoleEntry('info', t('run.consoleCancelRequested'));
    try {
      const cancelled = await session.sweepCancel(sweepId);
      if (!operationIsCurrent(requestId)) return;
      setSweepStatus(cancelled);
      setSweepSupervisionUnknown(cancelled.state === 'supervision_unknown');
      if (sweepStatusIsPollable(cancelled)) startSweepPolling(sweepId);
    } catch (e) {
      if (!operationIsCurrent(requestId)) return;
      if (e instanceof Error) { setSweepSupervisionUnknown(true); err(e, true); return; }
      throw e;
    } finally {
      if (!operationIsCurrent(requestId)) return;
      setSweepCancelling(false);
    }
  }

  return {
    doPreview, doRun, doCancel, resetSweepPlan,
    doSweepPreview, doSweepRun, doSweepCancel,
  };
}

export type RunActions = ReturnType<typeof useRunActions>;
