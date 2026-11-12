import { useEffect } from 'react';
import { runStatusIsPollable, sweepStatusIsPollable } from './runPolling';
import * as session from './session';
import { setRunConsoleSnapshot } from './runConsole';
import { cueRunOutcome } from './sound.mjs';
import { useLocale } from './i18n/index.ts';
import type { RunViewState } from './useRunViewState';

export function useRunLifecycle(state: RunViewState) {
  const { t } = useLocale();
  const {
    contextGeneration, mountedRef, operationRequestRef,
    runExecuteLockRef, sweepExecuteLockRef, poll,
    pollGenerationRef, pollRequestRef, sweepSupervisionUnknown, sweepId,
    setActive, setActiveLoaded, setDetect, setSelectedCandidateId,
    setPreview, setStatus, setStatusSource, setRunId, setSupervisionUnknown,
    setSweepSupervisionUnknown, setError, setErrorRetriesContext,
    setContextLoading, setContextUnavailable, setStarting, setSweepStatus,
    setContextGeneration,
  } = state;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      operationRequestRef.current.invalidate();
      runExecuteLockRef.current.reset();
      sweepExecuteLockRef.current.reset();
      stopPolling();
    };
  }, []);

  useEffect(() => {
    let disposed = false;

    const loadActiveCase = async () => {
      operationRequestRef.current.invalidate();
      runExecuteLockRef.current.reset();
      sweepExecuteLockRef.current.reset();
      stopPolling();
      setContextLoading(true);
      try {
        const activeCase = await session.fetchActiveCase();
        if (disposed) return;
        setContextUnavailable(false);
        setActive(activeCase);
        if (!activeCase.path) {
          setDetect(null);
          setSelectedCandidateId('');
          setPreview(null);
          setStatus(null);
          setRunId(null);
          setSupervisionUnknown(false);
          setSweepSupervisionUnknown(false);
          setError('');
          setErrorRetriesContext(false);
          return;
        }

        let contextError = '';
        if (!activeCase.path.toLowerCase().endsWith('.genkey')) {
          setDetect(null);
          setSelectedCandidateId('');
          setPreview(null);
          setStatus(null);
          setRunId(null);
          setSupervisionUnknown(false);
          setSweepSupervisionUnknown(false);
          setError(t('run.noActiveGenkey') ?? 'Select an active .genkey case before preparing an OLGA run.');
          setErrorRetriesContext(false);
          return;
        }

        try {
          const detection = await session.runDetect(activeCase.path);
          if (disposed) return;
          setDetect(detection);
          const selectedCandidate = detection.candidates.find((candidate) => candidate.candidate_id === detection.candidate_id);
          const nextCandidateId = selectedCandidate?.candidate_id ?? '';
          setSelectedCandidateId(nextCandidateId);
          setPreview((accepted) => accepted?.candidate_id === nextCandidateId ? accepted : null);
        } catch (cause) {
          if (disposed) return;
          contextError = cause instanceof Error
            ? t('run.detectionFailed', { cause: cause.message }) ?? `OLGA detection failed: ${cause.message}`
            : t('run.detectionFailedBare') ?? 'OLGA detection failed.';
        }

        try {
          const history = await session.fetchRunHistory(activeCase.path, 20);
          if (disposed) return;
          const restored = history[0] ?? null;
          setStatus(restored);
          setStatusSource(restored && !runStatusIsPollable(restored) ? 'history' : 'live');
          setRunId(restored?.run_id ?? null);
          if (restored && runStatusIsPollable(restored)) {
            setSupervisionUnknown(restored.state === 'supervision_unknown');
            startRunPolling(restored.run_id);
          } else {
            setSupervisionUnknown(false);
          }
        } catch (cause) {
          if (disposed) return;
          contextError = cause instanceof Error
            ? t('run.historyFailed', { cause: cause.message }) ?? `Run history loading failed: ${cause.message}`
            : t('run.historyFailedBare') ?? 'Run history loading failed.';
        }

        if (sweepSupervisionUnknown && sweepId) startSweepPolling(sweepId);

        setError(contextError);
        setErrorRetriesContext(Boolean(contextError));
      } catch (cause) {
        if (!disposed) {
          setError(cause instanceof Error
            ? t('run.activeCaseFailed', { cause: cause.message }) ?? `Active case loading failed: ${cause.message}`
            : t('run.activeCaseFailedBare') ?? 'Active case loading failed.');
          setErrorRetriesContext(true);
          setContextUnavailable(true);
        }
      } finally {
        if (!disposed) {
          setActiveLoaded(true);
          setContextLoading(false);
        }
      }
    };

    void loadActiveCase();
    return () => {
      disposed = true;
      operationRequestRef.current.invalidate();
      stopPolling();
    };
  }, [contextGeneration]);

  function clearError() {
    setError('');
    setErrorRetriesContext(false);
  }

  function err(cause: Error, retryContext = false) {
    setError(cause.message);
    setErrorRetriesContext(retryContext);
  }

  function retryRunContext() {
    stopPolling();
    operationRequestRef.current.invalidate();
    runExecuteLockRef.current.reset();
    sweepExecuteLockRef.current.reset();
    setContextGeneration((generation) => generation + 1);
  }

  function operationIsCurrent(requestId: number): boolean {
    return mountedRef.current && operationRequestRef.current.isCurrent(requestId);
  }

  function stopPolling() {
    if (poll.current) clearTimeout(poll.current);
    poll.current = null;
    pollGenerationRef.current.invalidate();
    pollRequestRef.current.invalidate();
  }

  function startRunPolling(id: string) {
    stopPolling();
    const generation = pollGenerationRef.current.begin();
    const tick = async () => {
      if (!pollGenerationRef.current.isCurrent(generation)) return;
      const requestId = pollRequestRef.current.begin();
      try {
        const next = await session.runStatus(id);
        if (!pollGenerationRef.current.isCurrent(generation) || !pollRequestRef.current.isCurrent(requestId)) return;
        setSupervisionUnknown(next.state === 'supervision_unknown');
        setStarting(false);
        setStatus(next);
        if (!runStatusIsPollable(next)) cueRunOutcome(next.run_id, next.state);
        setRunConsoleSnapshot({
          phase: next.solver_progress?.phase ?? null,
          simTimeS: next.solver_progress?.simulation_time_s ?? null,
          exitCode: next.exit_code,
          state: next.state,
          starting: false,
          logTail: next.log_tail ? next.log_tail.split(/\r?\n/).slice(-8) : [],
        });
        if (runStatusIsPollable(next)) {
          poll.current = window.setTimeout(() => { void tick(); }, 1500);
        } else {
          stopPolling();
        }
      } catch (e) {
        if (!pollGenerationRef.current.isCurrent(generation) || !pollRequestRef.current.isCurrent(requestId)) return;
        if (e instanceof Error) {
          setSupervisionUnknown(true);
          err(e, true);
          setStarting(false);
          stopPolling();
          return;
        }
        throw e;
      }
    };
    void tick();
  }

  function startSweepPolling(id: string) {
    stopPolling();
    const generation = pollGenerationRef.current.begin();
    const tick = async () => {
      if (!pollGenerationRef.current.isCurrent(generation)) return;
      const requestId = pollRequestRef.current.begin();
      try {
        const next = await session.sweepStatus(id);
        if (!pollGenerationRef.current.isCurrent(generation) || !pollRequestRef.current.isCurrent(requestId)) return;
        setSweepSupervisionUnknown(next.state === 'supervision_unknown');
        setSweepStatus(next);
        setRunConsoleSnapshot({ state: next.state, starting: false });
        if (sweepStatusIsPollable(next)) {
          poll.current = window.setTimeout(() => { void tick(); }, 1500);
        } else {
          stopPolling();
        }
      } catch (e) {
        if (!pollGenerationRef.current.isCurrent(generation) || !pollRequestRef.current.isCurrent(requestId)) return;
        if (e instanceof Error) {
          setSweepSupervisionUnknown(true);
          err(e, true);
          stopPolling();
          return;
        }
        throw e;
      }
    };
    void tick();
  }

  return {
    clearError, err, retryRunContext, operationIsCurrent,
    stopPolling, startRunPolling, startSweepPolling,
  };
}

export type RunLifecycle = ReturnType<typeof useRunLifecycle>;
