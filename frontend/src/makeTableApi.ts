import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

export type MakeTableResult = {
  readonly valid: boolean;
  readonly tab_name: string;
  readonly fluid_label: string;
  readonly grid_source: 'mfl' | 'default';
  readonly points: { readonly pressures: number; readonly temperatures: number };
};

/** The .mfl files in the case folder a missing table can be made from. Reads only. */
export async function makeTableCandidates(source: string): Promise<readonly string[]> {
  const body = (await jsonOrThrow(
    await apiFetch(`/api/fluids/make-tab/candidates?source=${encodeURIComponent(source)}`),
  )) as { mfl?: readonly { name: string }[] };
  return (body.mfl ?? []).map((item) => item.name);
}

/** Make the table with Multiflash. Only called from the explicit "Make the table" approve click. */
export async function makeTable(source: string, reference: string, mfl: string): Promise<MakeTableResult> {
  return (await jsonOrThrow(
    await apiFetch('/api/fluids/make-tab', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, reference, mfl, approved: true }),
    }),
  )) as MakeTableResult;
}
