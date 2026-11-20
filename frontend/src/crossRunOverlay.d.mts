import type { Series } from './resultContracts';
export type OverlayRefusal = { readonly key: 'overlay.refuse.empty' | 'overlay.refuse.dimension' | 'overlay.refuse.unit' | 'overlay.refuse.time'; readonly params: Record<string, string> };
export function overlayRefusal(base: Series | null | undefined, other: Series | null | undefined): OverlayRefusal | null;
