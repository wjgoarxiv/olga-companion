import type { ResultFile } from './session';

export type ResultInventorySnapshot = {
  readonly root: string;
  readonly results: readonly ResultFile[];
};

type ResultInventoryLoader = () => Promise<ResultInventorySnapshot>;

const MAX_CACHED_ROOTS = 3;
const cachedInventories = new Map<string, ResultInventorySnapshot>();
const inventoryRequests = new Map<string, Promise<ResultInventorySnapshot>>();
// Bumped by each scan that starts; only the newest scan of a root writes the cache.
const scanGenerations = new Map<string, number>();

function cloneInventory(inventory: ResultInventorySnapshot): { root: string; results: ResultFile[] } {
  return { root: inventory.root, results: [...inventory.results] };
}

export function readResultInventoryCache(root: string): { root: string; results: ResultFile[] } | null {
  const cached = cachedInventories.get(root);
  if (!cached) return null;
  cachedInventories.delete(root);
  cachedInventories.set(root, cached);
  return cloneInventory(cached);
}

export function writeResultInventoryCache(inventory: ResultInventorySnapshot): void {
  cachedInventories.delete(inventory.root);
  cachedInventories.set(inventory.root, cloneInventory(inventory));
  while (cachedInventories.size > MAX_CACHED_ROOTS) {
    const oldestRoot = cachedInventories.keys().next().value;
    if (typeof oldestRoot !== 'string') break;
    cachedInventories.delete(oldestRoot);
  }
}

export function fetchResultInventorySingleflight(
  root: string,
  loader: ResultInventoryLoader,
): Promise<{ root: string; results: ResultFile[] }> {
  const active = inventoryRequests.get(root);
  if (active) return active.then(cloneInventory);
  return startScan(root, loader);
}

/** A scan that does not join one already in flight: a run that just finished may be
    missing from an older scan. Later joiners share this one. */
export function rescanResultInventory(
  root: string,
  loader: ResultInventoryLoader,
): Promise<{ root: string; results: ResultFile[] }> {
  return startScan(root, loader);
}

function startScan(root: string, loader: ResultInventoryLoader): Promise<{ root: string; results: ResultFile[] }> {
  const generation = (scanGenerations.get(root) ?? 0) + 1;
  scanGenerations.set(root, generation);
  let request: Promise<ResultInventorySnapshot>;
  request = loader()
    .then((inventory) => {
      if (scanGenerations.get(root) === generation) writeResultInventoryCache(inventory);
      return cloneInventory(inventory);
    })
    .finally(() => {
      if (inventoryRequests.get(root) === request) inventoryRequests.delete(root);
    });
  inventoryRequests.set(root, request);
  return request.then(cloneInventory);
}

export function prefetchResultInventory(
  root: string,
  loader: ResultInventoryLoader,
): Promise<{ root: string; results: ResultFile[] }> {
  const cached = readResultInventoryCache(root);
  return cached ? Promise.resolve(cached) : fetchResultInventorySingleflight(root, loader);
}
