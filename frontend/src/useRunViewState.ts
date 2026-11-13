import { useRef, useState } from 'react';
import { createRequestEpoch, createSingleFlight } from './requestEpoch';
import * as session from './session';

export function useRunViewState() {
  const [active, setActive] = useState<session.ActiveCase | null>(null);
  const [activeLoaded, setActiveLoaded] = useState(false);
  const [detect, setDetect] = useState<session.OlgaDetection | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState('');
  // Whole hours; the preview's approval is bound to the limit it was built with.
  const [timeoutHours, setTimeoutHours] = useState(1);
  const [preview, setPreview] = useState<session.RunPreview | null>(null);
  // The preview an approved run was started from; a finished or uncertain run needs a fresh one.
  const [usedSelectionId, setUsedSelectionId] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<session.RunStatus | null>(null);
  // 'history': a receipt restored from an earlier session, not a run started in this view.
  const [statusSource, setStatusSource] = useState<'history' | 'live'>('live');
  const [previewing, setPreviewing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [sweepParameter, setSweepParameter] = useState('INTEGRATION.ENDTIME');
  const [sweepValues, setSweepValues] = useState('3600,7200');
  const [sweepPreview, setSweepPreview] = useState<session.SweepStatus | null>(null);
  const [sweepId, setSweepId] = useState<string | null>(null);
  const [sweepStatus, setSweepStatus] = useState<session.SweepStatus | null>(null);
  const [sweepPreviewing, setSweepPreviewing] = useState(false);
  const [sweepStarting, setSweepStarting] = useState(false);
  const [sweepCancelling, setSweepCancelling] = useState(false);
  const [error, setError] = useState('');
  const [errorRetriesContext, setErrorRetriesContext] = useState(false);
  const [contextGeneration, setContextGeneration] = useState(0);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextUnavailable, setContextUnavailable] = useState(false);
  const [supervisionUnknown, setSupervisionUnknown] = useState(false);
  const [sweepSupervisionUnknown, setSweepSupervisionUnknown] = useState(false);
  const poll = useRef<number | null>(null);
  const pollGenerationRef = useRef(createRequestEpoch());
  const pollRequestRef = useRef(createRequestEpoch());
  const mountedRef = useRef(false);
  const operationRequestRef = useRef(createRequestEpoch());
  const runExecuteLockRef = useRef(createSingleFlight());
  const sweepExecuteLockRef = useRef(createSingleFlight());

  return {
    active, setActive, activeLoaded, setActiveLoaded, detect, setDetect,
    selectedCandidateId, setSelectedCandidateId, timeoutHours, setTimeoutHours, preview, setPreview, usedSelectionId, setUsedSelectionId,
    runId, setRunId, status, setStatus, statusSource, setStatusSource, previewing, setPreviewing,
    starting, setStarting, cancelling, setCancelling,
    sweepParameter, setSweepParameter, sweepValues, setSweepValues,
    sweepPreview, setSweepPreview, sweepId, setSweepId,
    sweepStatus, setSweepStatus, sweepPreviewing, setSweepPreviewing,
    sweepStarting, setSweepStarting, sweepCancelling, setSweepCancelling,
    error, setError, errorRetriesContext, setErrorRetriesContext,
    contextGeneration, setContextGeneration, contextLoading, setContextLoading,
    contextUnavailable, setContextUnavailable,
    supervisionUnknown, setSupervisionUnknown,
    sweepSupervisionUnknown, setSweepSupervisionUnknown,
    poll, pollGenerationRef, pollRequestRef, mountedRef, operationRequestRef,
    runExecuteLockRef, sweepExecuteLockRef,
  };
}

export type RunViewState = ReturnType<typeof useRunViewState>;
