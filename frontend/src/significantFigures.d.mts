export const SIGNIFICANT_FIGURE_OPTIONS: readonly [3, 4, 5, 6];
export type SignificantFigures = (typeof SIGNIFICANT_FIGURE_OPTIONS)[number];
export const DEFAULT_SIGNIFICANT_FIGURES: SignificantFigures;
export const SIGNIFICANT_FIGURES_KEY: string;

export type PreferenceStorage = {
  readonly getItem: (key: string) => string | null;
  readonly setItem: (key: string, value: string) => void;
};

export function parseSignificantFigures(value: unknown): SignificantFigures | null;
export function loadSignificantFigures(storage?: PreferenceStorage): SignificantFigures;
export function saveSignificantFigures(significantFigures: SignificantFigures, storage?: PreferenceStorage): boolean;
export function formatSignificant(value: number, significantFigures: number): string;
export function figuresForSpan(minimum: number, maximum: number, significantFigures: number): number;
export function formatDistinctTicks(values: readonly number[], significantFigures: number): string[];
