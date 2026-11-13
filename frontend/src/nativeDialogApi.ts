import { createNativeContextRequestPayload } from './nativeDialogRequest';
import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';
import type { WorkspaceContext } from './workspaceApi';

export interface NativeSelectedContext extends WorkspaceContext {
  readonly status: 'selected';
  readonly revoked: number;
}

export type NativeDialogTerminal =
  | { readonly status: 'cancelled' }
  | { readonly status: 'unavailable'; readonly reason: string };

export type NativeContextDialogResult =
  | NativeSelectedContext
  | NativeDialogTerminal
  | { readonly status: 'superseded' };

export type NativeSaveAsResult =
  | { readonly status: 'selected'; readonly basename: string; readonly size: number; readonly reveal_id?: string }
  | NativeDialogTerminal;

export type NativeDialogCancelResult =
  | { readonly status: 'cancelled'; readonly request_id?: string }
  | { readonly status: 'unavailable'; readonly reason: string };

export async function chooseNativeWorkspace(requestId: string, contextGeneration: number): Promise<NativeContextDialogResult> {
  return (await jsonOrThrow(
    await apiFetch('/api/native-dialogs/workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(createNativeContextRequestPayload(requestId, contextGeneration)),
    }),
  )) as NativeContextDialogResult;
}

export async function openNativeCase(requestId: string, contextGeneration: number): Promise<NativeContextDialogResult> {
  return (await jsonOrThrow(
    await apiFetch('/api/native-dialogs/open-case', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(createNativeContextRequestPayload(requestId, contextGeneration)),
    }),
  )) as NativeContextDialogResult;
}

export async function revealSavedReport(revealId: string): Promise<void> {
  if (!/^[0-9a-f]{32}$/.test(revealId)) {
    throw new Error('reveal_refused');
  }
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('reveal_saved_report', { revealId });
}

export async function saveArtifactAs(requestId: string, artifact: string, initialPath?: string): Promise<NativeSaveAsResult> {
  return (await jsonOrThrow(
    await apiFetch('/api/native-dialogs/save-as', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId, artifact, ...(initialPath ? { initial_path: initialPath } : {}) }),
    }),
  )) as NativeSaveAsResult;
}

export async function cancelNativeDialog(requestId: string, options?: { readonly keepalive?: boolean }): Promise<NativeDialogCancelResult> {
  return (await jsonOrThrow(
    await apiFetch('/api/native-dialogs/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId }),
      keepalive: options?.keepalive,
    }),
  )) as NativeDialogCancelResult;
}

export interface SaveAsRecoveryStatus {
  readonly id: string;
  readonly status: 'available' | 'missing';
  readonly basename: string;
  readonly backup_available: boolean;
  readonly time: string;
}

export async function fetchSaveAsRecoveryStatus(recoveryId: string, signal?: AbortSignal): Promise<SaveAsRecoveryStatus> {
  return (await jsonOrThrow(
    await apiFetch(`/api/native-dialogs/save-as/recovery/${encodeURIComponent(recoveryId)}`, {
      signal,
    }),
  )) as SaveAsRecoveryStatus;
}
