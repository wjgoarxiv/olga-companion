import { useLayoutEffect, useState } from 'react';

/** Rendered width of an SVG, so its viewBox can match it and text keeps its CSS size. */
export function useMeasuredWidth(minimum: number, fallback: number) {
  const [element, setElement] = useState<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(fallback);
  // Layout effect: measure before first paint so the chart never flashes at the fallback width.
  useLayoutEffect(() => {
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const measure = () => setWidth(Math.max(minimum, Math.round(element.getBoundingClientRect().width)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element, minimum]);
  return { width, setElement };
}

/** Left margin that fits the longest y tick label plus a rotated axis title. */
export function yAxisMargin(longestLabelChars: number, fontPx: number, minimum: number): number {
  return Math.max(minimum, Math.ceil(longestLabelChars * fontPx * 0.62) + 44);
}
