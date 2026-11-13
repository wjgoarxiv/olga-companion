export type FocusScheduler = (callback: () => void) => () => void;

export function scheduleFocusReturn(
  target: HTMLElement | null,
  schedule?: FocusScheduler,
  fallback?: () => HTMLElement | null,
): () => void;

export function scheduleIdleFocusReturn(
  target: HTMLElement | null,
  schedule?: FocusScheduler,
  getActive?: () => Element | null,
): () => void;
