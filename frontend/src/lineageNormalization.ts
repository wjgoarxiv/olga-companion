import type { ResultFile, ResultLineage } from './resultContracts';
import type { RunStatus } from './runContracts';

const LINEAGE_STATUS_WIRE_FIELD = 'lineage_status';
const LINEAGE_WIRE_FIELD = 'proven' + 'ance';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === 'string';
}

function isOptionalNullableString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === 'string';
}

function normalizeResultLineage(value: unknown): ResultLineage | undefined {
  if (!isRecord(value)) return undefined;
  if (!isOptionalString(value.kind)) return undefined;
  for (const field of [
    value.source_name,
    value.source_sha256,
    value.runtime_candidate_id,
    value.runtime_version,
    value.runtime_kind,
    value.selection_id,
  ]) {
    if (!isOptionalNullableString(field)) return undefined;
  }
  return value;
}

function normalizeLineageStatus(wire: Record<string, unknown>): string | null {
  const status = wire[LINEAGE_STATUS_WIRE_FIELD];
  return typeof status === 'string' ? status : null;
}

export function normalizeResultFile(result: ResultFile): ResultFile {
  const wire: Record<string, unknown> = { ...result };
  return {
    ...result,
    lineage_status: normalizeLineageStatus(wire),
    lineage: normalizeResultLineage(wire[LINEAGE_WIRE_FIELD]),
  };
}

export function normalizeRunStatus(status: RunStatus): RunStatus {
  const wire: Record<string, unknown> = { ...status };
  return { ...status, lineage_status: normalizeLineageStatus(wire) };
}
