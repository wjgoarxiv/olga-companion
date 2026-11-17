import type { SolverProgress } from './session';

export function progressAttributes(
  fraction: number | null | undefined,
  vendorPercent: number | null | undefined,
): { readonly max: 1; readonly value?: number };

export interface EffectiveSolverProgress extends SolverProgress {
  readonly last_known: boolean;
  readonly last_known_phase: SolverProgress['phase'] | null;
}

export function effectiveSolverProgress(
  progress: SolverProgress,
  supervisionUnknown: boolean,
): EffectiveSolverProgress;

export interface ChatActivityInput {
  readonly phase: string;
  readonly started_at_ms: number;
  readonly now_ms: number;
  readonly cancellable: boolean;
  readonly reduced_motion: boolean;
}

export interface ChatActivityPresentation {
  readonly phase: string;
  readonly label: string;
  readonly elapsed_ms: number;
  readonly can_cancel: boolean;
  readonly motion: 'static' | 'animated';
}

export function presentChatActivity(input: ChatActivityInput): ChatActivityPresentation;

export function eventActivityPhase(event: {
  readonly type: string;
  readonly data: Record<string, unknown>;
}): string;

export function localizeActivity(
  activity: ChatActivityPresentation,
  t: (key: string) => string,
): ChatActivityPresentation;
