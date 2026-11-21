export type DisplayQuantity = {
  readonly value: number | unknown;
  readonly unit: string;
  readonly raw: string;
  readonly converted: boolean;
};

export function toDisplay(value: unknown, rawUnit: string | null | undefined): DisplayQuantity;
export function toDisplayDelta(value: unknown, rawUnit: string | null | undefined): DisplayQuantity;
export function toRaw(shown: number, rawUnit: string | null | undefined): number;
export function displayText(quantity: DisplayQuantity): string;
export function displayFromText(text: unknown): string;
