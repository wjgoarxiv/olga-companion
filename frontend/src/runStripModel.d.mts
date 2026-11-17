export const STRIP_LINGER_MS: number;
export type RunStripTone = 'running' | 'finalizing' | 'stopping' | 'unknown' | 'completed' | 'failed';
export type RunStripView =
  | { readonly visible: false }
  | {
      readonly visible: true;
      readonly runId: string;
      readonly caseName: string;
      readonly tone: RunStripTone;
      readonly percent: number | null;
      readonly simTimeS: number | null;
      readonly elapsedS: number | null;
      readonly etaS: number | null;
      readonly canStop: boolean;
      readonly canOpenResults: boolean;
    };
export function runStripModel(
  observation: { readonly kind: string; readonly status?: unknown } | null | undefined,
  clock: { readonly now: number; readonly terminalSince: number | null },
): RunStripView;
export function durationParts(seconds: number): { h: number; m: number; s: number; total: number };
