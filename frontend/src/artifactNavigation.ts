export const OPEN_ARTIFACT_IN_RESULTS_EVENT = 'olga:open-result-artifact' as const;

export type OpenArtifactRequest = {
  readonly artifactId: string;
  readonly resultId: string;
};

export type OpenArtifactEventDetail = {
  readonly artifact_id: string;
  readonly result_id: string;
};

export class ArtifactIdentityError extends Error {
  readonly name = 'ArtifactIdentityError';
  readonly field: 'artifact_id' | 'result_id';

  constructor(field: 'artifact_id' | 'result_id') {
    super(`Invalid ${field}.`);
    this.field = field;
  }
}

function parseArtifactId(value: string): string {
  if (/^artifact_[0-9a-f]{32}$/.test(value)) return value;
  throw new ArtifactIdentityError('artifact_id');
}

function parseResultId(value: string): string {
  if (value.length > 4_096 || value.includes('\\') || /[\u0000-\u001f\u007f]/.test(value)) {
    throw new ArtifactIdentityError('result_id');
  }
  const match = /^(workspace|run):(.+)$/.exec(value);
  if (!match) throw new ArtifactIdentityError('result_id');
  const relative = match[2];
  if (!relative || relative.includes(':') || relative.startsWith('/') || relative.endsWith('/')) {
    throw new ArtifactIdentityError('result_id');
  }
  const segments = relative.split('/');
  if (segments.some((segment) => !segment || segment === '.' || segment === '..')) {
    throw new ArtifactIdentityError('result_id');
  }
  return value;
}

export function parseOpenArtifactEventDetail(value: unknown): OpenArtifactEventDetail {
  if (typeof value !== 'object' || value === null) {
    throw new ArtifactIdentityError('result_id');
  }
  const candidate = value as Partial<OpenArtifactEventDetail>;
  if (typeof candidate.artifact_id !== 'string' || typeof candidate.result_id !== 'string') {
    throw new ArtifactIdentityError('result_id');
  }
  return {
    artifact_id: parseArtifactId(candidate.artifact_id),
    result_id: parseResultId(candidate.result_id),
  };
}

export function requestOpenArtifactInResults(
  request: OpenArtifactRequest,
  target: EventTarget = window,
): void {
  const detail = parseOpenArtifactEventDetail({
    artifact_id: parseArtifactId(request.artifactId),
    result_id: parseResultId(request.resultId),
  });
  target.dispatchEvent(new CustomEvent<OpenArtifactEventDetail>(OPEN_ARTIFACT_IN_RESULTS_EVENT, { detail }));
}
