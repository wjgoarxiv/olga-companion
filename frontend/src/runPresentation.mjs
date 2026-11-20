const FAULT_LINE = /error|fatal|abort|exception|fail|cannot|can't|unable|invalid|terminat|exceeded|license/iu;
const MAX_LINE = 200;

/** Lines of a solver log tail that explain a stop, or its last lines when none do. */
export function solverLogHighlights(tail, limit = 5) {
  const lines = String(tail ?? '').split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
  const faults = lines.filter((line) => FAULT_LINE.test(line));
  const picked = faults.length > 0 ? faults.slice(-limit) : lines.slice(-Math.min(3, limit));
  return {
    kind: faults.length > 0 ? 'fault' : 'last-lines',
    lines: picked.map((line) => (line.length > MAX_LINE ? `${line.slice(0, MAX_LINE)}…` : line)),
  };
}

/** The status that may drive live UI (progress, header state); a restored receipt is history. */
export function liveRunStatus(status, source) {
  return source === 'live' ? status : null;
}

/**
 * A run the operator cancelled or that hit its time limit is a stop, not a case failure:
 * its nonzero child exit code (Windows 1223 / 1460) says nothing about the case, so the
 * stored solver-failure text must not be shown for it. Null for every other state.
 */
export function runStopNotice(status, t) {
  if (status.state === 'cancelled') {
    return {
      title: t('run.stopCancelledTitle'),
      detail: t('run.stopCancelledDetail'),
      action: null,
    };
  }
  if (status.state === 'timed_out') {
    return {
      title: t('run.stopTimedOutTitle'),
      detail: t('run.stopTimedOutDetail'),
      action: t('run.stopTimedOutAction'),
    };
  }
  return null;
}

/** What the operator can do next. Never an automatic retry of an uncertain run. */
export function runNextAction(status, supervisionUnknown = false, t = null) {
  const text = (key) => (typeof t === 'function' ? t(key) : null);
  if (supervisionUnknown || status.state === 'supervision_unknown') {
    return text('run.nextUnknown') ?? '실행 상태를 확인할 수 없습니다. 같은 실행을 자동으로 다시 시작하지 않습니다. “Retry run context”로 상태를 다시 읽으세요.';
  }
  switch (status.state) {
    case 'recovery_unknown':
      return text('run.nextRecovery') ?? '프로세스와 종료 기록을 모두 찾지 못했습니다. 같은 실행을 자동으로 다시 시작하지 않습니다. 필요하면 사례를 확인한 뒤 새로 미리보기하세요.';
    case 'completed':
      if (status.outputs?.some((output) => output.suffix?.toLowerCase() === '.tpl')) {
        return text('run.nextCompletedTpl') ?? 'Results에서 TPL을 열어 변수와 단위를 확인하세요.';
      }
      return status.outputs?.length
        ? text('run.nextCompletedNoTpl') ?? 'TPL 결과가 없어 그래프를 만들 수 없습니다. 기록된 출력 파일과 로그를 확인하세요.'
        : text('run.nextCompletedEmpty') ?? '기록된 결과 파일이 없습니다. 로그를 확인하세요.';
    case 'timed_out':
      return text('run.nextTimedOut') ?? '제한 시간을 늘린 뒤 미리보기부터 새로 승인해 다시 실행하세요. 같은 실행은 자동으로 다시 시작되지 않습니다.';
    case 'failed':
      return text('run.nextFailed') ?? '위 오류 줄을 확인한 뒤 Chat에서 원인 분석을 요청하거나, 수정한 사본으로 다시 미리보기하세요. 같은 실행은 자동으로 다시 시작되지 않습니다.';
    case 'cancelled':
      return text('run.nextCancelled') ?? '사용자가 중지했습니다. 다시 실행하려면 미리보기부터 새로 승인하세요.';
    default:
      return null;
  }
}

/** Why Approve and run is disabled, in the order the operator can resolve it. */
export function approveBlockedReason({ operationActive, runReady, preview, usedSelectionId = '', t = null }) {
  const text = (key) => (typeof t === 'function' ? t(key) : null);
  if (operationActive) return text('run.blockedBusy') ?? '다른 작업이 진행 중입니다. 끝나면 다시 시도할 수 있습니다.';
  if (!runReady) return text('run.blockedNotReady') ?? 'OLGA 실행 환경이 확인되지 않았습니다. 위 런타임 안내를 확인하세요.';
  if (!preview?.selection_id) return text('run.blockedNoPreview') ?? '먼저 “Preview command”로 실행할 명령을 확인하세요.';
  if (!preview.validation?.valid) return text('run.blockedInvalidPreview') ?? '사례 검증이 실패했습니다. 오류를 해결한 뒤 다시 미리보기하세요.';
  if (usedSelectionId && preview.selection_id === usedSelectionId) return text('run.blockedAlreadyStarted') ?? '이 미리보기로 이미 실행을 시작했습니다. 다시 실행하려면 “Preview command”로 새 미리보기를 만드세요.';
  return '';
}

