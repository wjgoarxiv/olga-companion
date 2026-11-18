const HEAD_CHARS = 8;
const TAIL_CHARS = 12;

/** Middle-ellipsis for file stems: keep the head for orientation and the tail
 *  that distinguishes `…_vent` from `…_vent_endtime60`. The full name always
 *  stays on the element's title/aria-label; this only shortens display text. */
export function displayStem(stem: string): string {
  if (stem.length <= HEAD_CHARS + TAIL_CHARS + 1) return stem;
  return `${stem.slice(0, HEAD_CHARS)}…${stem.slice(-TAIL_CHARS)}`;
}

/** Split a stem into head/tail halves for CSS-only middle truncation: the
 *  head ellipsizes only when it really overflows, the tail never shrinks, and
 *  the halves rejoin to the full stem whenever space allows. The tail is kept
 *  short on purpose so the visible head still reaches mid-name variants in a
 *  140 px track (e.g. `spacing_demo_a…_line` vs `spacing_demo_b…_line`). */
const SPLIT_TAIL_CHARS = 5;

export function splitNameHalves(stem: string): { readonly head: string; readonly tail: string } {
  if (stem.length <= HEAD_CHARS + SPLIT_TAIL_CHARS + 1) return { head: stem, tail: '' };
  return { head: stem.slice(0, -SPLIT_TAIL_CHARS), tail: stem.slice(-SPLIT_TAIL_CHARS) };
}
