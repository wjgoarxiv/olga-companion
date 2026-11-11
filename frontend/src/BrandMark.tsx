/**
 * The OLGA Companion mark: a Terminalcore prompt glyph, `>_` in the accent
 * colour followed by a block cursor in the second accent.
 *
 * Rects and one stepped path on a 16-unit integer grid, so it needs no font and
 * every edge lands on a pixel boundary at 16, 32 and 48 px. Geometry is kept in
 * step with assets/logo/mark.svg and assets/logo/mark-tile.svg; the fallbacks
 * are the night-theme Tokyo Night values and only apply where a token is unset.
 *
 * Decorative: the surrounding control carries the accessible name, so the SVG is
 * hidden from assistive technology and not focusable. No ids, so any number of
 * copies can share a screen.
 */
export default function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
      shapeRendering="crispEdges"
    >
      <g style={{ fill: 'var(--accent, #7aa2f7)' }}>
        <path d="M2 4H4V5H5V6H6V7H7V9H6V10H5V11H4V12H2V11H3V10H4V9H5V7H4V6H3V5H2Z" />
        <rect x="8" y="10" width="3" height="2" />
      </g>
      <rect x="12" y="4" width="2" height="8" style={{ fill: 'var(--accent-2, #9ece6a)' }} />
    </svg>
  );
}
