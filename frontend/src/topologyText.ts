export const TOPO_LABEL_BASE_PX = 13;
export const TOPO_LABEL_MIN_UNITS = 12;
export const TOPO_LABEL_MAX_UNITS = 18;

/** Label size in SVG user units that renders near the base pixel size.
 *  A small fitted graph on a wide canvas would otherwise blow labels up. */
export function nodeLabelFontSize(viewW: number, canvasW: number): number {
  if (!Number.isFinite(viewW) || !Number.isFinite(canvasW) || canvasW <= 0 || viewW <= 0) {
    return TOPO_LABEL_BASE_PX;
  }
  const units = (TOPO_LABEL_BASE_PX * viewW) / canvasW;
  return Math.min(TOPO_LABEL_MAX_UNITS, Math.max(TOPO_LABEL_MIN_UNITS, units));
}

export function pickCountKey(base: 'workspace.node' | 'workspace.flowpath', count: number): string {
  return `${base}_${count === 1 ? 'one' : 'other'}`;
}
