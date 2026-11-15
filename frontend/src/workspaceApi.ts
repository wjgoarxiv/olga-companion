import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

export interface WorkspaceCase {
  name: string;
  rel: string;
  size: number;
  suffix: string;
}

export interface ActiveCase {
  name: string | null;
  path: string | null;
}

export interface WorkspaceContext {
  readonly root: string;
  readonly cases: WorkspaceCase[];
  readonly active: ActiveCase;
  readonly generation: number;
}

export async function fetchWorkspace(): Promise<{ root: string; cases: WorkspaceCase[] }> {
  return (await jsonOrThrow(await apiFetch('/api/workspace/list'))) as {
    root: string;
    cases: WorkspaceCase[];
  };
}

export async function fetchActiveCase(): Promise<ActiveCase> {
  return (await jsonOrThrow(await apiFetch('/api/workspace/active'))) as ActiveCase;
}

export async function fetchWorkspaceContext(): Promise<WorkspaceContext> {
  return (await jsonOrThrow(
    await apiFetch('/api/workspace/context'),
  )) as WorkspaceContext;
}

export async function setActiveCase(rel: string, contextGeneration: number): Promise<ActiveCase> {
  return (await jsonOrThrow(
    await apiFetch('/api/workspace/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rel, context_generation: contextGeneration }),
    }),
  )) as ActiveCase;
}

export interface Topology {
  path: string;
  nodes: { id: string; label: string; kind: string }[];
  edges: { source: string; target: string; label: string; kind: string }[];
  counts: { nodes: number; flowpaths: number; edges: number };
  truncated: boolean;
}

export interface FlowpathPipe {
  label: string;
  nsegment: number;
  diameter_m: number;
  total_length_m: number;
  volume_m3: number;
  section_range: [number, number];
  start?: FlowpathPoint;
  end?: FlowpathPoint;
}

export interface FlowpathPoint {
  x_m: number;
  y_m: number;
  z_m: number;
}

export interface FlowpathSection {
  section_index: number;
  pipe_section_index: number;
  pipe_label: string;
  length_m: number;
  diameter_m: number;
  chainage_start_m: number;
  chainage_end_m: number;
  start: FlowpathPoint;
  center: FlowpathPoint;
  end: FlowpathPoint;
}

export interface FlowpathDetails {
  schema_version: 2;
  flowpath: string;
  geometry:
    | { status: 'ready'; coordinate_unit: 'm'; start: FlowpathPoint; source?: 'length_elevation' }
    | { status: 'unavailable'; reason: string };
  summary: {
    pipe_count: number;
    segment_count: number;
    total_length_m: number;
    total_volume_m3: number;
    diameter_min_m: number | null;
    diameter_max_m: number | null;
  };
  pipes: FlowpathPipe[];
  sections: FlowpathSection[];
}

/** The parsed network graph for a workspace case — feeds the topology canvas directly. */
export async function fetchTopology(rel: string): Promise<Topology> {
  return (await jsonOrThrow(
    await apiFetch('/api/genkey/topology', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rel }),
    }),
  )) as Topology;
}

/** One validator finding; the validator returns objects, not plain strings. */
export interface TabValidationFinding {
  readonly rule_id?: string;
  readonly severity?: string;
  readonly category?: string;
  readonly message?: string;
  readonly location?: string;
  readonly suggestion?: string;
}

export interface TabPreview {
  readonly path: string;
  readonly valid: boolean;
  readonly summary_text: string;
  readonly parsed?: Record<string, unknown> | null;
  readonly validation_errors?: readonly TabValidationFinding[];
  readonly validation_warnings?: readonly TabValidationFinding[];
  readonly source_mutated?: boolean;
}

/** Read-only PVT table preview for a `.tab` support file. */
export async function inspectTab(path: string): Promise<TabPreview> {
  return (await jsonOrThrow(
    await apiFetch('/api/fluids/inspect-tab', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),
  )) as TabPreview;
}

export interface FluidDraftComponent {
  readonly name: string;
  readonly mole_fraction: number;
}

export interface FluidDraftInput {
  readonly fluid_label: string;
  readonly components: readonly FluidDraftComponent[];
  readonly model: string;
  readonly temperatures: readonly number[];
  readonly temperature_unit: string;
  readonly pressures: readonly number[];
  readonly pressure_unit: string;
  readonly mfl_rel: string;
}

export interface FluidDraftPreview {
  readonly mfl_rel: string;
  readonly tab_abs: string;
  // No separate table-line field: the shown mfl_text already embeds the
  // `table Olga ...` line, and this module stays free of execution tokens.
  readonly mfl_text: string;
  readonly writes_nothing: boolean;
}

/** Read-only .mfl draft preview: validates the composition server-side and
    returns the exact file text. Writes nothing by contract. */
export async function fluidsDraftPreview(input: FluidDraftInput): Promise<FluidDraftPreview> {
  return (await jsonOrThrow(
    await apiFetch('/api/fluids/draft-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...input, hawater: false, tab_rel: null }),
    }),
  )) as FluidDraftPreview;
}

export interface FluidOpenResult {
  readonly launched?: boolean;
  readonly exe?: string;
  readonly mfl_path?: string | null;
  readonly message?: string;
}

/** Launch the bundled Multiflash GUI. Called only from the explicit
    "Open in Multiflash" click (approved: true marks that click). */
export async function fluidsOpenMultiflash(mflPath: string | null): Promise<FluidOpenResult> {
  return (await jsonOrThrow(
    await apiFetch('/api/fluids/open-multiflash', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mfl_path: mflPath, approved: true }),
    }),
  )) as FluidOpenResult;
}

export interface FluidPickupResult {
  readonly found: boolean;
  readonly valid: boolean;
  readonly declared_label: string | null;
  readonly label_match: boolean;
  readonly errors: readonly { readonly message?: string }[];
  readonly warnings: readonly { readonly message?: string }[];
  readonly link_proposal: {
    readonly tab_path: string;
    readonly fluid_label: string | null;
    readonly next_steps: string;
  } | null;
}

/** Validate the produced .tab (read-only) and check its label. Given an .mfl
    path the backend resolves the expected .tab from the draft itself. */
export async function fluidsPickupTab(path: string, fluidLabel: string | null): Promise<FluidPickupResult> {
  return (await jsonOrThrow(
    await apiFetch('/api/fluids/pickup-tab', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, fluid_label: fluidLabel }),
    }),
  )) as FluidPickupResult;
}

export async function fetchFlowpathDetails(
  rel: string,
  flowpath: string,
  signal?: AbortSignal,
): Promise<FlowpathDetails> {
  return (await jsonOrThrow(
    await apiFetch('/api/genkey/flowpath-details', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rel, flowpath }),
      signal,
    }),
  )) as FlowpathDetails;
}
