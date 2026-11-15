// Pure state helpers for the xAI (Grok) device-code connect UI.
export const XAI_POLL_MS = 3000;

const TERMINAL = new Set(['connected', 'denied', 'expired', 'error']);

export function isTerminalXaiState(state) {
  return TERMINAL.has(state);
}

const COPY = {
  idle: { title: '아직 연결되지 않았습니다.', action: 'xAI 연결' },
  starting: { title: '연결을 시작하는 중입니다.', action: 'xAI 연결' },
  pending: { title: '아래 코드를 브라우저에서 입력하세요.', action: '다시 시작' },
  connected: { title: 'xAI에 연결되었습니다.', action: '연결 해제' },
  denied: { title: '승인이 거부되었습니다.', action: 'xAI 연결' },
  expired: { title: '코드가 만료되었습니다.', action: 'xAI 연결' },
  error: { title: '연결하지 못했습니다.', action: 'xAI 연결' },
};

export function xaiConnectCopy(state, message) {
  const base = COPY[state] ?? COPY.idle;
  return state === 'error' && message ? { ...base, title: message } : base;
}
