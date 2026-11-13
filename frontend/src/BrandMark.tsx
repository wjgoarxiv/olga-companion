/**
 * The OLGA Companion mark: a Terminalcore prompt glyph, `>_` in the accent
 * colour followed by a block cursor in the second accent.
 *
 * Smooth stroked paths with round caps and joins on a 16-unit grid, so the
 * mark stays clean at any size with no anti-aliasing steps. Geometry is kept
 * in step with assets/logo/mark.svg and assets/logo/mark-tile.svg; the
 * fallbacks are the night-theme Tokyo Night values and only apply where a
 * token is unset.
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
    >
      <g
        fill="none"
        stroke="var(--accent, #7aa2f7)"
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M3.5 4.5 7 8l-3.5 3.5" />
        <path d="M8.5 11.5h3" />
      </g>
      <rect x="12" y="4" width="2" height="8" rx="1" style={{ fill: 'var(--accent-2, #9ece6a)' }} />
    </svg>
  );
}
