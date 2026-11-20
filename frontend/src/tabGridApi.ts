import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';
import type { TabGrid } from './pvtGrid';

export async function fetchTabGrid(path: string, column?: string): Promise<TabGrid> {
  return (await jsonOrThrow(
    await apiFetch('/api/fluids/tab-grid', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(column ? { path, column } : { path }),
    }),
  )) as TabGrid;
}
