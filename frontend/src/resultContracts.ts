export interface ResultLineage {
  readonly kind?: string;
  readonly source_name?: string | null;
  readonly source_sha256?: string | null;
  readonly runtime_candidate_id?: string | null;
  readonly runtime_version?: string | null;
  readonly runtime_kind?: string | null;
  readonly selection_id?: string | null;
}

export interface ResultFile {
  readonly id: string;
  readonly result_id?: string;
  readonly name: string;
  readonly rel: string;
  readonly origin: 'workspace' | 'run';
  readonly size: number;
  readonly suffix: string;
  readonly modified_ns: number;
  readonly run_id?: string;
  readonly run_state?: string;
  readonly run_ok?: boolean;
  readonly source_name?: string | null;
  readonly source_sha256?: string | null;
  readonly runtime_kind?: string | null;
  readonly runtime_version?: string | null;
  readonly runtime_candidate_id?: string | null;
  readonly output_sha256?: string | null;
  readonly lineage_status?: string | null;
  readonly lineage?: ResultLineage;
}

export interface ResultVar {
  index: number;
  variable: string;
  position: string;
  unit: string;
  description: string;
}

export type QuantityKind = 'point' | 'delta';

export type SeriesRangeSpec =
  | { readonly mode: 'full' }
  | { readonly mode: 'tail'; readonly fraction: 0.25 | 0.1 }
  | { readonly mode: 'bounds'; readonly start: number; readonly end: number };

export interface SeriesViewSpec {
  readonly value_unit?: string;
  readonly time_unit?: string;
  readonly quantity_kind: QuantityKind;
  readonly range: SeriesRangeSpec;
}

export interface ConversionMetadata {
  readonly status: 'not_requested' | 'identity' | 'converted' | 'source_only';
  readonly source_unit: string | null;
  readonly requested_unit: string | null;
  readonly output_unit: string | null;
  readonly dimension: string | null;
  readonly quantity_kind: QuantityKind;
  readonly reason: string | null;
  readonly reference_semantics?: string;
}

export interface SeriesViewMetadata {
  readonly value_conversion: ConversionMetadata;
  readonly time_conversion: ConversionMetadata;
  readonly range: {
    readonly mode: 'full' | 'tail' | 'bounds';
    readonly fraction?: number;
    readonly start?: number;
    readonly end?: number;
    readonly samples?: number;
  };
}

export interface SeriesAnalysis {
  scope: 'descriptive';
  samples: number;
  start_time: number;
  end_time: number;
  minimum: number;
  maximum: number;
  mean: number;
  initial: number;
  final: number;
  delta: number;
  percent_change: number | null;
  peak_time: number;
  direction: 'increasing' | 'decreasing' | 'stable';
}

export interface Series {
  variable: string;
  unit: string | null;
  description: string | null;
  position: string | null;
  time: number[];
  values: number[];
  time_unit: string | null;
  analysis: SeriesAnalysis;
  view: SeriesViewMetadata;
}

export interface PublicationExport {
  ok: boolean;
  plots: string[];
  documents: string[];
  publication: { dpi: number; font_family: string; font_path: string; style_source: string };
  analysis: SeriesAnalysis;
  view?: SeriesViewMetadata;
}

export interface CsvExport {
  readonly variable: string;
  readonly position: string;
  readonly unit: string | null;
  readonly download_path: string;
  readonly row_count: number;
}

export type ChatSeriesRow = {
  readonly time: number;
  readonly value: number;
};

export type ChatSeriesReceipt = {
  readonly variable: string;
  readonly units: { readonly time: string; readonly value: string };
  readonly position: string | null;
  readonly row_limit: number;
  readonly total_rows: number;
  readonly returned_rows: number;
  readonly rows: readonly ChatSeriesRow[];
  readonly time_range: { readonly start: number; readonly end: number };
  readonly source_sha256: string;
  readonly truncated: boolean;
  readonly truncation: 'head' | 'tail' | 'uniform';
  readonly analysis: {
    readonly minimum: number;
    readonly maximum: number;
    readonly mean: number;
  };
  readonly lineage: Readonly<Record<string, unknown>>;
};

export type ArtifactKind = 'csv' | 'png' | 'pdf';
export type ArtifactMime = 'text/csv' | 'image/png' | 'application/pdf';
export type ArtifactReceiptAction = 'download' | 'open_in_results' | 'native_save_as';

export type ArtifactReceipt = {
  readonly artifact_id: string;
  readonly kind: ArtifactKind;
  readonly mime: ArtifactMime;
  readonly size_bytes: number;
  readonly sha256: string;
  readonly suggested_filename: string;
  readonly lineage: Readonly<Record<string, unknown>>;
  readonly workspace_generation: number;
  readonly actions: readonly ArtifactReceiptAction[];
};
