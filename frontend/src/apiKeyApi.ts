import { apiFetch } from './sessionTransport';

export type ApiKeyProtocol = 'openai-responses' | 'openai-chat';

export type ApiKeyConnection = {
  readonly id: string;
  readonly label: string;
  readonly protocol: ApiKeyProtocol;
  readonly base_url: string;
  readonly model: string;
  readonly has_key: boolean;
  readonly last4: string;
  readonly verified: boolean;
  readonly last_outcome: string | null;
};

export async function fetchApiKeyConnections(): Promise<ApiKeyConnection[]> {
  const body = (await (await apiFetch('/api/providers/apikey')).json()) as {
    connections: ApiKeyConnection[];
  };
  return body.connections;
}

export async function saveApiKeyConnection(input: {
  label: string;
  protocol: ApiKeyProtocol;
  base_url: string;
  model: string;
  key: string;
}): Promise<{ id: string; outcome: string }> {
  const response = await apiFetch('/api/providers/apikey', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return (await response.json()) as { id: string; outcome: string };
}

export async function verifyApiKeyConnection(id: string): Promise<{ outcome: string }> {
  const response = await apiFetch(`/api/providers/apikey/${encodeURIComponent(id)}/verify`, {
    method: 'POST',
  });
  return (await response.json()) as { outcome: string };
}

export async function deleteApiKeyConnection(id: string): Promise<{ deleted: boolean }> {
  const response = await apiFetch(`/api/providers/apikey/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  return (await response.json()) as { deleted: boolean };
}
