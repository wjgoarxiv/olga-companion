function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** FastAPI 422 detail is an array of {loc,msg} objects; flatten to readable text
 *  (the v0.1 "[object Object]" bug came from stringifying it raw). */
function flattenDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry: unknown) => {
        const record = isRecord(entry) ? entry : {};
        const loc = Array.isArray(record.loc)
          ? record.loc.filter((part: unknown) => part !== 'body').join('.')
          : '';
        const message = typeof record.msg === 'string' ? record.msg : 'Invalid request';
        return loc ? `${loc}: ${message}` : message;
      })
      .join('; ');
  }
  if (isRecord(detail) && typeof detail.message === 'string') return detail.message;
  return '';
}

export class SaveAsRecoveryError extends Error {
  readonly code = 'save_as_recovery_required';
  readonly recoveryId: string;

  constructor(message: string, recoveryId: string) {
    super(message);
    this.name = 'SaveAsRecoveryError';
    this.recoveryId = recoveryId;
  }
}

export async function jsonOrThrow(response: Response): Promise<unknown> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = isRecord(body) ? body.detail : undefined;
    if (
      isRecord(detail)
      && detail.code === 'save_as_recovery_required'
      && typeof detail.message === 'string'
      && typeof detail.recovery_id === 'string'
    ) {
      throw new SaveAsRecoveryError(detail.message.slice(0, 512), detail.recovery_id.slice(0, 128));
    }
    throw new Error(flattenDetail(detail) || `HTTP ${response.status}`);
  }
  return body;
}
