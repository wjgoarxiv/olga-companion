import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

export interface ProviderSelection {
  readonly provider: string;
  readonly model: string;
  readonly variant: string;
}

function isSelection(value: unknown): value is ProviderSelection {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return typeof record.provider === 'string'
    && typeof record.model === 'string'
    && typeof record.variant === 'string';
}

export async function loadProviderSelection(): Promise<ProviderSelection | null> {
  const body: unknown = await jsonOrThrow(await apiFetch('/api/llm-selection'));
  if (!isSelection(body) || !body.provider || !body.model) return null;
  return { provider: body.provider, model: body.model, variant: body.variant || 'medium' };
}

export async function saveProviderSelection(selection: ProviderSelection): Promise<void> {
  await jsonOrThrow(await apiFetch('/api/llm-selection', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      provider: selection.provider,
      model: selection.model,
      variant: selection.variant,
    }),
  }));
}
