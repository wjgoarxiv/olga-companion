import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

export interface LocalCliResult {
  readonly code: string;
  readonly version: string;
  readonly override?: boolean;
  readonly billing?: 'subscription' | 'api_key' | 'unknown';
  readonly message_ko: string;
  readonly message_en: string;
}

export async function fetchLocalCliStatus(fresh = false): Promise<LocalCliResult> {
  const path = fresh ? '/api/providers/claude_cli/status?fresh=1' : '/api/providers/claude_cli/status';
  return (await jsonOrThrow(await apiFetch(path))) as LocalCliResult;
}

export async function checkLocalCli(): Promise<LocalCliResult> {
  return (await jsonOrThrow(await apiFetch('/api/providers/claude_cli/check', { method: 'POST' }))) as LocalCliResult;
}
