export declare const BOOT_TIMEOUT_MS: number;
export declare const BOOT_POLL_BASE_MS: number;
export declare const BOOT_POLL_MAX_MS: number;
export declare const BOOT_STAGES: readonly string[];

export type BootStage = 'starting' | 'connecting' | 'ready' | 'failed';
export type BootFailReason = 'offline' | 'timeout' | 'unavailable';

export declare function bootPollDelayMs(attempt: number): number;

export type BootGateEvent =
  | 'health_ok'
  | 'ready_ok'
  | 'transport_failed'
  | 'exhausted'
  | 'fail_unavailable'
  | 'retry';

export interface BootGate {
  event(name: BootGateEvent): string;
  checkTimeout(): boolean;
  phase(): string;
  reason(): string | null;
  isReady(): boolean;
  isFailed(): boolean;
  isPending(): boolean;
  elapsedMs(): number;
}

export declare function createBootGate(options?: {
  now?: () => number;
  timeoutMs?: number;
}): BootGate;
