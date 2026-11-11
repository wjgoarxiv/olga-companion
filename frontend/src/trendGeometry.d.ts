export interface TrendPoint {
  readonly index: number;
  readonly time: number;
  readonly value: number;
  readonly segment: number;
  readonly move: boolean;
  readonly x: number;
  readonly y: number;
}

export interface TrendGeometry {
  readonly points: readonly TrendPoint[];
  readonly path: string;
  readonly xDomain: readonly [number, number] | null;
  readonly yDomain: readonly [number, number] | null;
  readonly finiteCount: number;
  readonly xAt: (value: number) => number;
  readonly yAt: (value: number) => number;
}

export interface InspectionNavigation {
  readonly indices: readonly number[];
  readonly ordinalByIndex: ReadonlyMap<number, number>;
}

export function buildTrendGeometry(
  time: readonly number[],
  values: readonly number[],
  options?: { readonly width?: number; readonly height?: number; readonly pointBudget?: number },
): TrendGeometry;

export function createNearestPointLookup(
  time: readonly number[],
  values: readonly number[],
): { readonly strategy: 'binary' | 'linear'; readonly find: (target: number) => number | null };
export function createInspectionNavigation(time: readonly number[], values: readonly number[]): InspectionNavigation;
export function transitionInspection(
  key: string,
  currentIndex: number | null,
  navigation: InspectionNavigation,
): { readonly handled: boolean; readonly nextIndex: number | null };
export function finiteSampleOrdinal(index: number, navigation: InspectionNavigation): number | null;

export const TREND_VIEW_WIDTH: number;
export const TREND_VIEW_HEIGHT: number;
export const TREND_GUTTER_LEFT: number;
export const TREND_GUTTER_RIGHT: number;
export interface ViewBoxFit {
  readonly scale: number;
  readonly drawnWidth: number;
  readonly drawnHeight: number;
  readonly offsetX: number;
  readonly offsetY: number;
}
export function fitViewBoxLetterbox(rectWidth: number, rectHeight: number, viewWidth?: number, viewHeight?: number): ViewBoxFit;
export function clientToDataX(
  clientX: number,
  rectLeft: number,
  rectWidth: number,
  rectHeight: number,
  xMin: number,
  xMax: number,
): number;

export function niceTicks(minimum: number, maximum: number, targetCount?: number): number[];
export function ticksWithin(ticks: readonly number[], minimum: number, maximum: number): number[];
export function applyBrushDomain(
  time: readonly number[],
  values: readonly number[],
  start: number,
  end: number,
): { readonly time: readonly number[]; readonly values: readonly number[] };
export function pickAutoPlotVariable<T extends { readonly variable?: unknown }>(variables: readonly T[]): T | null;
