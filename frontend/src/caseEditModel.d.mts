export type CaseEditField =
  | 'end_time_s'
  | 'pressure_pa'
  | 'temperature_c'
  | 'mass_flow_kg_s'
  | 'opening'
  | 'roughness_m'
  | 'diameter_m'
  | 'max_dt_s'
  | 'min_dt_s'
  | 'dt_start_s'
  | 'trend_interval_s'
  | 'profile_interval_s'
  | 'output_interval_s'
  | 'ambient_temperature_c'
  | 'outer_heat_transfer_coefficient_w_m2k'
  | 'wall_thickness_m'
  | 'wall_conductivity_w_mk'
  | 'wall_heat_capacity_j_kgk'
  | 'wall_density_kg_m3'
  | 'setpoint'
  | 'gain'
  | 'integral_s'
  | 'derivative_s';

export type CaseEditRow = {
  readonly id: string;
  readonly target: string;
  readonly field: CaseEditField;
  readonly value: number | null;
  readonly unit: string;
  readonly op: Readonly<Record<string, string>>;
  readonly note?: 'schedule' | 'series' | 'derived' | 'unset';
  /** The OLGA KEYWORD.KEY the row changes, e.g. PARAMETERS.SETPOINT. */
  readonly keyword?: string;
};

export type CellResult = { ok: true; value: number } | { ok: false; error: string };
export type BuildResult =
  | { ok: true; operations: Record<string, unknown>[] }
  | { ok: false; rowId: string | null; error: string };

export function cellField(row: CaseEditRow): string;
export function displayUnit(field: string): string;
export function withUnit(row: CaseEditRow, shown: string): string;
export function unitInBrackets(row: CaseEditRow): string;
export function displayValue(row: CaseEditRow): number;
export function formatDisplay(row: CaseEditRow): string;
export function parseCell(field: string, text: string): CellResult;
export function changedRows(rows: readonly CaseEditRow[], drafts: Readonly<Record<string, string>>): CaseEditRow[];
export function buildOperations(rows: readonly CaseEditRow[], drafts: Readonly<Record<string, string>>): BuildResult;
export function conflictKey(code: string): string | null;
export function planReasons(plan: unknown): string[];
export function planWarnings(plan: unknown): string[];
export function planWarningCount(plan: unknown): number;
