export interface UnitPreferences {
  readonly version: 1;
  readonly valueUnits: Readonly<Record<string, string>>;
  readonly timeUnit: string | null;
}

export interface PreferenceStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export const UNIT_PREFERENCES_VERSION: 1;
export const UNIT_PREFERENCES_KEY: string;
export function loadUnitPreferences(storage?: PreferenceStorage): UnitPreferences;
export function saveUnitPreferences(storage: PreferenceStorage | undefined, preferences: UnitPreferences): boolean;
export function setValueUnitPreference(preferences: UnitPreferences, dimension: string, unit: string): UnitPreferences;
export function setTimeUnitPreference(preferences: UnitPreferences, unit: string): UnitPreferences;
export function unitChoicesForDimension(dimension: string | null | undefined): string[];
export function preferredSeriesView(
  preferences: UnitPreferences,
  valueConversion: { readonly dimension?: string | null; readonly source_unit?: string | null },
  timeConversion: { readonly dimension?: string | null; readonly source_unit?: string | null },
): {
  readonly value_unit?: string;
  readonly time_unit?: string;
  readonly quantity_kind: 'point';
  readonly range: { readonly mode: 'full' };
};
export function discoveryMatchesPreferredView(
  discovered: {
    readonly unit?: string | null;
    readonly time_unit?: string | null;
    readonly view?: {
      readonly value_conversion?: { readonly status?: string; readonly output_unit?: string | null; readonly quantity_kind?: string };
      readonly time_conversion?: { readonly status?: string; readonly output_unit?: string | null };
      readonly range?: { readonly mode?: string };
    };
  },
  preferredView: {
    readonly value_unit?: string;
    readonly time_unit?: string;
    readonly quantity_kind: 'point' | 'delta';
    readonly range: { readonly mode: string };
  },
): boolean;
export function acceptSeriesUnitPreferences(
  preferences: UnitPreferences,
  valueConversion: { readonly status?: string; readonly dimension?: string | null; readonly output_unit?: string | null },
  timeConversion: { readonly status?: string; readonly dimension?: string | null; readonly output_unit?: string | null },
): UnitPreferences;
