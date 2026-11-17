export interface RequestEpoch {
  begin(): number;
  isCurrent(request: number): boolean;
  invalidate(): void;
}

export function createRequestEpoch(): RequestEpoch;

export interface SingleFlight {
  begin(): number | null;
  end(request: number): void;
  reset(): void;
}

export function createSingleFlight(): SingleFlight;
