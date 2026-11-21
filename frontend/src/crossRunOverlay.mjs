// Whether the same variable from another run may share the chart: same dimension, same shown
// unit and quantity kind, same time unit. A unit the app cannot read is refused, not assumed.

const text = (value) => (typeof value === 'string' ? value : '');

/** null when the other series may join the chart; else an i18n key with both sides named. */
export function overlayRefusal(base, other) {
  if (!other || !Array.isArray(other.time) || other.time.length === 0) return { key: 'overlay.refuse.empty', params: {} };
  const bv = base?.view?.value_conversion ?? {};
  const ov = other.view?.value_conversion ?? {};
  if (bv.dimension && ov.dimension && bv.dimension !== ov.dimension) {
    return { key: 'overlay.refuse.dimension', params: { a: bv.dimension, b: ov.dimension } };
  }
  const bu = text(bv.output_unit) || text(base?.unit);
  const ou = text(ov.output_unit) || text(other.unit);
  if (!bu || !ou || bu !== ou || (bv.quantity_kind ?? 'point') !== (ov.quantity_kind ?? 'point')) {
    return { key: 'overlay.refuse.unit', params: { a: bu || '?', b: ou || '?' } };
  }
  const bt = text(base?.view?.time_conversion?.output_unit) || text(base?.time_unit);
  const ot = text(other.view?.time_conversion?.output_unit) || text(other.time_unit);
  if (!bt || !ot || bt !== ot) return { key: 'overlay.refuse.time', params: { a: bt || '?', b: ot || '?' } };
  return null;
}
