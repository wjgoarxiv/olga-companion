export declare const OVERLAY_BAND_QUERY: string;
export declare function isOverlayBandWidth(width: number): boolean;
export declare function inOverlayBandNow(): boolean;
export declare function revealCentreView<View>(
  deps: { readonly inBand: boolean; readonly closeDock: () => void; readonly selectView: (view: View) => void },
  view: View,
): void;
export declare function resolveOverlayExclusive(
  open: { readonly dockOpen: boolean; readonly explorerOpen: boolean },
  changed: 'dock' | 'explorer' | null,
  inBand: boolean,
): { readonly dockOpen: boolean; readonly explorerOpen: boolean };
