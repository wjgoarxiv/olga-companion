/** Pixel corner marks for a pane frame. Gradients only, no text, no hit target. */
export function PaneDecor() {
  return (
    <>
      <i className="pane-mark pane-mark-tl" aria-hidden="true" />
      <i className="pane-mark pane-mark-tr" aria-hidden="true" />
      <i className="pane-mark pane-mark-bl" aria-hidden="true" />
      <i className="pane-mark pane-mark-br" aria-hidden="true" />
    </>
  );
}
