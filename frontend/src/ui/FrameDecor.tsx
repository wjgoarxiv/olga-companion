/** Static technical decor for a framed canvas: ruler ticks along the top and
    left edges and crosshair marks in the corners. Pure paint, hidden from
    assistive tech, never animated. The parent needs `position: relative`. */
export function FrameDecor() {
  return (
    <>
      <i className="frame-ruler frame-ruler-x" aria-hidden="true" />
      <i className="frame-ruler frame-ruler-y" aria-hidden="true" />
      <i className="frame-mark frame-mark-tl" aria-hidden="true" />
      <i className="frame-mark frame-mark-tr" aria-hidden="true" />
      <i className="frame-mark frame-mark-bl" aria-hidden="true" />
      <i className="frame-mark frame-mark-br" aria-hidden="true" />
    </>
  );
}
