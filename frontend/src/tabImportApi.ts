import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';
import type { TabImportPreview } from './tabImport';

export interface TabImportPreviewInput {
  readonly path: string;
  readonly fluidLabel: string;
  readonly waterFraction: number | null;
}

/** Read-only: summarises a workspace CSV/XLSX as a .tab. The file itself is written only by the approval card. */
export async function tabImportPreview(input: TabImportPreviewInput): Promise<TabImportPreview> {
  return (await jsonOrThrow(await apiFetch('/api/fluids/tab-import/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path: input.path,
      fluid_label: input.fluidLabel,
      total_water_fraction: input.waterFraction,
    }),
  }))) as TabImportPreview;
}
