import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

export interface XaiLoginStatus {
  readonly state: 'idle' | 'pending' | 'connected' | 'denied' | 'expired' | 'error';
  readonly message: string;
  readonly user_code?: string;
  readonly verification_uri?: string;
  readonly verification_uri_complete?: string;
  readonly expires_at?: number;
}

export interface XaiLoginStart {
  readonly user_code: string;
  readonly verification_uri: string;
  readonly verification_uri_complete: string;
  readonly expires_at: number;
}

export async function startXaiLogin(): Promise<XaiLoginStart> {
  return (await jsonOrThrow(await apiFetch('/api/providers/xai/login', { method: 'POST' }))) as XaiLoginStart;
}

export async function fetchXaiLoginStatus(): Promise<XaiLoginStatus> {
  return (await jsonOrThrow(await apiFetch('/api/providers/xai/login/status'))) as XaiLoginStatus;
}

export async function logoutXai(): Promise<XaiLoginStatus> {
  return (await jsonOrThrow(await apiFetch('/api/providers/xai/logout', { method: 'POST' }))) as XaiLoginStatus;
}
