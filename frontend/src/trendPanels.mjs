// Which plotted series share a chart panel. Series in one displayed unit share an axis; a series in
// another unit gets its own panel, so a 0–1 controller output is not flattened next to a pressure.

const unitOf = (item) => String(item.series?.unit ?? '').trim();

/** Panels in display order: the active series' panel first, then each other unit in plotted order. */
export function trendPanels(plotted, activeKey, oneAxis) {
  const active = plotted.find((item) => item.key === activeKey);
  if (!active) return [];
  if (oneAxis) return [{ key: active.key, primary: active, overlays: plotted.filter((item) => item !== active) }];
  const groups = new Map([[unitOf(active), [active]]]);
  for (const item of plotted) {
    if (item === active) continue;
    const unit = unitOf(item);
    if (!groups.has(unit)) groups.set(unit, []);
    groups.get(unit).push(item);
  }
  return [...groups.values()].map(([primary, ...overlays]) => ({ key: primary.key, primary, overlays }));
}

/** [first, last] time over every plotted series, so stacked panels line up; null when none is finite. */
export function sharedTimeSpan(plotted) {
  let low = Infinity;
  let high = -Infinity;
  for (const item of plotted) {
    for (const time of item.series?.time ?? []) {
      if (!Number.isFinite(time)) continue;
      if (time < low) low = time;
      if (time > high) high = time;
    }
  }
  return low <= high ? [low, high] : null;
}
