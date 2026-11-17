export const XAI_POLL_MS: number;
export type XaiLoginState = 'idle' | 'starting' | 'pending' | 'connected' | 'denied' | 'expired' | 'error';
export function isTerminalXaiState(state: string): boolean;
export function xaiConnectCopy(state: string, message?: string): { title: string; action: string };
