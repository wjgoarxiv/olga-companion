const STATE_ORDER = { missing: 0, warn: 1, ok: 2 };

/** Missing values first, then warnings, then passes; the server's order is kept inside a state. */
export function orderedItems(items) {
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => (STATE_ORDER[a.item.state] ?? 1) - (STATE_ORDER[b.item.state] ?? 1) || a.index - b.index)
    .map(({ item }) => item);
}

/** The click that opens the item's edit-table row of this case, or null when it names no row. */
export function rowOpener(rel, item, open) {
  if (!item.row_id) return null;
  return () => open(rel, item.row_id);
}
