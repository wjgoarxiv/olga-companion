export type PlacedPoint = { readonly x: number; readonly y: number };
export type FitSize = { readonly nodeW: number; readonly nodeH: number; readonly pad: number };
export type ContentView = { readonly x: number; readonly y: number; readonly w: number; readonly h: number };

/** Initial viewBox hugging placed nodes plus padding. Pan/zoom stay untouched;
 *  this only decides what the map opens on so the diagram fills its box. */
export function fitContentView(points: readonly PlacedPoint[], size: FitSize): ContentView {
  if (points.length === 0) {
    return { x: 0, y: 0, w: 400, h: 200 };
  }
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const point of points) {
    minX = Math.min(minX, point.x);
    minY = Math.min(minY, point.y);
    maxX = Math.max(maxX, point.x + size.nodeW);
    maxY = Math.max(maxY, point.y + size.nodeH);
  }
  return {
    x: minX - size.pad,
    y: minY - size.pad,
    w: maxX - minX + size.pad * 2,
    h: maxY - minY + size.pad * 2,
  };
}
