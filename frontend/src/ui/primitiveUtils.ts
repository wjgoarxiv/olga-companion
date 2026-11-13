/** Shared roving-index and filter math for the workbench primitives. */

export type RovingOrientation = 'horizontal' | 'vertical' | 'both';

/** Next index for arrow/Home/End navigation over a fixed list, wrapping. */
export function moveRovingIndex(
  current: number,
  count: number,
  key: string,
  orientation: RovingOrientation = 'horizontal',
): number {
  if (count <= 0) return 0;
  const forward = orientation === 'vertical'
    ? key === 'ArrowDown'
    : orientation === 'horizontal'
      ? key === 'ArrowRight'
      : key === 'ArrowRight' || key === 'ArrowDown';
  const backward = orientation === 'vertical'
    ? key === 'ArrowUp'
    : orientation === 'horizontal'
      ? key === 'ArrowLeft'
      : key === 'ArrowLeft' || key === 'ArrowUp';
  if (forward) return (current + 1) % count;
  if (backward) return (current - 1 + count) % count;
  if (key === 'Home') return 0;
  if (key === 'End') return count - 1;
  return current;
}

export interface PaletteFilterItem {
  readonly label: string;
  readonly keywords?: string;
}

/** Case-insensitive substring filter over labels plus optional keywords. */
export function filterPaletteItems<T extends PaletteFilterItem>(items: readonly T[], query: string): T[] {
  const needle = query.trim().toLowerCase();
  if (needle === '') return [...items];
  return items.filter((item) =>
    item.label.toLowerCase().includes(needle)
    || (item.keywords ?? '').toLowerCase().includes(needle),
  );
}
