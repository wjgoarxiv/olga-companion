export interface OlgaCandidate {
  readonly candidate_id: string;
  readonly runtime_id: string;
  readonly exe: string;
  readonly version: string | null;
  readonly kind: string | null;
  readonly source: string;
}

export interface OlgaDetectionEvidence {
  readonly source_type: string;
  readonly version: string;
  readonly path: string;
  readonly strength: 'strong' | 'stale';
  readonly input_file: string;
  readonly bytes_read: number;
  readonly normal_stop?: boolean;
}

export type OlgaSelectionStatus =
  | 'not_found'
  | 'conflicting_evidence'
  | 'missing_required_version'
  | 'override_version_mismatch'
  | 'override_not_found'
  | 'selected_override'
  | 'selected'
  | 'selected_fallback';

export interface OlgaDetection {
  readonly detected: boolean;
  readonly source: string | null;
  readonly exe: string | null;
  readonly kind: string | null;
  readonly searched: readonly string[];
  readonly version: string | null;
  readonly candidate_id: string | null;
  readonly runtime_id: string | null;
  readonly selection_status: OlgaSelectionStatus;
  readonly rationale: string;
  readonly reason_code?: string | null;
  readonly reason_params?: Readonly<Record<string, string | number | readonly (string | number)[]>> | null;
  readonly required_version: string | null;
  readonly candidates: readonly OlgaCandidate[];
  readonly alternatives: readonly OlgaCandidate[];
  readonly evidence: readonly OlgaDetectionEvidence[];
  readonly case_source: string | null;
}

export type RunFailure = {
  readonly code: string;
  readonly title: string;
  readonly detail: string;
  readonly action: string;
  readonly auto_retry_safe: false;
  readonly solver_findings?: readonly SolverFinding[];
};

export type SolverFinding = {
  readonly code: string;
  readonly message: string;
  readonly evidence: string;
  readonly line: number | null;
  readonly time: number | null;
  readonly suggestion: string | null;
};

export interface RunOutput {
  readonly name: string;
  readonly suffix: string;
  readonly size: number;
  readonly sha256: string;
  readonly path: string;
  readonly result_id?: string;
}

export interface SolverProgress {
  readonly parse_status: 'parsed' | 'missing' | 'empty' | 'unreadable' | 'malformed' | 'indeterminate';
  readonly activity_status: 'active' | 'stale' | 'unavailable' | 'terminal' | 'clock_skew';
  readonly observed_at: string;
  readonly file_timestamp: string | null;
  readonly age_seconds: number | null;
  readonly simulation_time_s: number | null;
  readonly step: number | null;
  readonly adaptive_total_steps: number | null;
  readonly step_size_s: number | null;
  readonly vendor_percent: number | null;
  readonly fraction: number | null;
  readonly phase: 'running' | 'finalizing' | 'terminal' | 'supervision_unknown' | 'indeterminate';
  readonly liveness: 'supervised' | 'terminal' | 'supervision_unknown' | 'indeterminate';
  readonly files: {
    readonly out: string | null;
    readonly run_log: string | null;
  };
  readonly evidence: {
    readonly timestep: string;
    readonly vendor_percent: string;
  };
}

export interface RunStatus {
  readonly run_id: string;
  readonly state: string;
  readonly exit_code: number | null;
  readonly ok: boolean;
  readonly engine_failed: boolean;
  readonly log_tail: string;
  readonly command: readonly string[];
  readonly source_name?: string;
  readonly candidate_id?: string | null;
  readonly runtime_id?: string | null;
  readonly version?: string | null;
  readonly kind?: string | null;
  readonly detection?: OlgaDetection;
  readonly selection_id?: string;
  readonly validation_valid?: boolean;
  readonly outputs: readonly RunOutput[];
  readonly recovered_from_receipt?: boolean;
  readonly recovery?: string | null;
  readonly lineage_status?: string | null;
  readonly failure: RunFailure | null;
  readonly solver_findings?: readonly SolverFinding[];
  readonly elapsed_ms: number;
  readonly cancel_requested: boolean;
  readonly solver_progress: SolverProgress;
  readonly collection_pending?: boolean;
}

export interface RunPreview {
  readonly source: string;
  readonly selection_id: string;
  readonly candidate_id: string;
  readonly runtime_id?: string;
  readonly detection: OlgaDetection;
  readonly display_command: readonly string[];
  readonly cwd_template: string;
  readonly timeout_s: number;
  readonly validation: {
    readonly valid: boolean;
    readonly command: Record<string, unknown>;
  };
}
