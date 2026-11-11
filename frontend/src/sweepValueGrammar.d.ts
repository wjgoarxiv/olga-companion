export declare const MAX_SWEEP_CASES: 20;

export type SweepRangeInput = {
  readonly start: number;
  readonly stop: number;
  readonly count: number;
  readonly unit: string;
};

export declare function splitSweepValues(value: string): readonly string[];
export declare function buildRangeSweepValues(input: SweepRangeInput): string;
export declare function readRangeSweepValues(value: string, fallback: SweepRangeInput): SweepRangeInput;
