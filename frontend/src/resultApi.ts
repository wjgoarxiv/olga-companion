import { normalizeResultFile } from './lineageNormalization';
import type {
  CsvExport,
  PublicationExport,
  ResultFile,
  ResultVar,
  Series,
  SeriesViewSpec,
} from './resultContracts';
import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

/** OLGA output files (.tpl/.ppl) under the workspace root. */
export async function fetchResults(): Promise<{ root: string; results: ResultFile[] }> {
  const body = (await jsonOrThrow(await apiFetch('/api/workspace/results'))) as {
    root: string;
    results: ResultFile[];
  };
  return { root: body.root, results: body.results.map(normalizeResultFile) };
}

export interface FindingJudgement {
  readonly criterion: string;
  readonly verdict?: string;
  readonly status?: string;
  readonly missing?: readonly string[];
  readonly source_file?: string;
  readonly source_sha256?: string;
  readonly variables?: readonly string[];
  readonly timestep?: unknown;
  readonly mapping?: Readonly<Record<string, unknown>>;
  readonly formula?: string;
  readonly threshold?: Readonly<Record<string, unknown>>;
  readonly measured?: Readonly<Record<string, unknown>>;
}

export interface FindingsResponse {
  readonly judgements: readonly FindingJudgement[];
  readonly pending: readonly FindingJudgement[];
  readonly count: number;
}

export interface FindingsMarkdown {
  readonly markdown: string;
  readonly filename: string;
  readonly artifact: string;
}

/** Build a findings report and stage it for the native Save As dialog. */
export async function createFindingsReport(body: {
  readonly case_file: string;
  readonly results_file: string;
  readonly verdicts: readonly FindingJudgement[];
  readonly figures: readonly string[];
  readonly variables: readonly string[];
  readonly run_id?: string;
}): Promise<FindingsMarkdown> {
  return (await jsonOrThrow(
    await apiFetch('/api/reports/findings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )) as FindingsMarkdown;
}

/** Read-only engineering judgements with full citations. Never launches runs. */
export async function evaluateFindings(
  criteria: ReadonlyArray<{ kind: string; params: Readonly<Record<string, unknown>> }>,
): Promise<FindingsResponse> {
  return (await jsonOrThrow(
    await apiFetch('/api/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ criteria }),
    }),
  )) as FindingsResponse;
}

/** A result file's variable list + metadata. */
export interface LoadedResult {
  readonly ok: boolean;
  readonly variables: ResultVar[];
  readonly file_type: string;
  /** Present for .ppl: the branches and profile times available to plot. */
  readonly branches?: readonly string[];
  readonly timesteps?: readonly number[];
}

export async function loadResultVars(
  path: string,
): Promise<LoadedResult> {
  return (await jsonOrThrow(
    await apiFetch('/api/results/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),
  )) as LoadedResult;
}

/** One variable's time series for the interactive trend chart. */
export async function fetchSeries(
  rel: string,
  variable: string,
  position?: string,
  view?: SeriesViewSpec,
): Promise<Series> {
  return (await jsonOrThrow(
    await apiFetch('/api/results/series', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rel, variable, position, ...(view ? view : {}) }),
    }),
  )) as Series;
}

export interface Profile {
  readonly path: string;
  readonly variable: string;
  readonly branch: string;
  readonly timestep: number | null;
  readonly timestep_unit: string | null;
  readonly positions: readonly number[];
  readonly values: readonly number[];
  readonly unit: string | null;
  readonly description?: string | null;
}

/** Spatial profile for one `.ppl` variable on one branch at one time. */
export async function fetchProfile(
  rel: string,
  variable: string,
  branch: string,
  timestep?: number,
): Promise<Profile> {
  return (await jsonOrThrow(
    await apiFetch('/api/results/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rel, variable, branch, timestep }),
    }),
  )) as Profile;
}

export async function exportPublicationPlot(
  path: string,
  variable: string,
  position: string,
  view?: SeriesViewSpec,
): Promise<PublicationExport> {
  return (await jsonOrThrow(
    await apiFetch('/api/results/plot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, variables: [variable], position, ...(view ? view : {}) }),
    }),
  )) as PublicationExport;
}

export async function exportSelectedCsv(
  path: string,
  variable: string,
  position: string,
  view?: SeriesViewSpec,
): Promise<CsvExport> {
  return (await jsonOrThrow(
    await apiFetch('/api/results/extract-csv', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, variables: [variable], position, ...(view ? view : {}) }),
    }),
  )) as CsvExport;
}

/* Profile exports reuse the existing endpoints and payload shapes: branch and
 * timestep are already optional fields on both contracts, so a .ppl request
 * simply omits `position` (CSV) or `position`/`view` (figure). */
export async function exportProfileCsv(
  path: string,
  variable: string,
  branch: string,
  timestep?: number,
): Promise<{ readonly ok: boolean; readonly csv: string | null }> {
  return (await jsonOrThrow(
    await apiFetch('/api/results/extract-csv', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(
        timestep === undefined || timestep === null
          ? { path, variables: [variable], branch }
          : { path, variables: [variable], branch, timestep },
      ),
    }),
  )) as { readonly ok: boolean; readonly csv: string | null };
}

export async function exportProfilePlot(path: string, variable: string, branch: string): Promise<PublicationExport> {
  return (await jsonOrThrow(
    await apiFetch('/api/results/plot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, variables: [variable], branch }),
    }),
  )) as PublicationExport;
}

export function resultDownloadUrl(path: string): string {
  return `/api/results/download?path=${encodeURIComponent(path)}`;
}

export class ArtifactDownloadError extends Error {
  readonly name = 'ArtifactDownloadError';
  readonly artifactId: string;

  constructor(artifactId: string) {
    super('Artifact download could not be completed.');
    this.artifactId = artifactId;
  }
}

export function artifactDownloadUrl(artifactId: string): string {
  if (!/^artifact_[0-9a-f]{32}$/.test(artifactId)) throw new ArtifactDownloadError(artifactId);
  return `/api/artifacts/${encodeURIComponent(artifactId)}/download`;
}

export async function downloadArtifact(artifactId: string, signal?: AbortSignal): Promise<Blob> {
  const response = await apiFetch(artifactDownloadUrl(artifactId), { signal });
  if (response.ok) return response.blob();
  await jsonOrThrow(response);
  throw new ArtifactDownloadError(artifactId);
}

export class ResultImageError extends Error {
  readonly name = 'ResultImageError';

  constructor(readonly path: string) {
    super('Result image could not be loaded.');
  }
}

export async function fetchResultImage(path: string, signal?: AbortSignal): Promise<Blob> {
  const response = await apiFetch(resultDownloadUrl(path), { signal });
  if (response.ok) return response.blob();
  await jsonOrThrow(response);
  throw new ResultImageError(path);
}
