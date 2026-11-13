/** Display helpers. The app should never make the user read a filesystem path —
 *  the whole reason v2 exists is to stop exposing raw paths and capability
 *  plumbing. `basename` leads with the file's name; the full path stays
 *  available on hover (title attr) for the one place trust needs it: approvals. */
export function basename(p: string): string {
  if (!p) return '';
  const parts = p.split(/[/\\]/).filter(Boolean);
  return parts[parts.length - 1] || p;
}

/** Compact a value for the evidence key/value read-out. A read-out cell is a
 *  single scannable line, never a wall: newlines collapse to spaces and the
 *  result is hard-capped, so a long multi-line field (a 2 KB summary, an ASCII
 *  topology dump, a raw object) can't blow the timeline to thousands of pixels.
 *  Long, human-readable text belongs in the <pre> viewer (see EvidenceBlock
 *  textFields), not here. Paths collapse to their basename. */
export function compactValue(v: unknown, max = 200): string {
  const oneLine = rawCompact(v).replace(/\s+/g, ' ').trim();
  return oneLine.length > max ? `${oneLine.slice(0, max)}…` : oneLine;
}

function rawCompact(v: unknown): string {
  if (v == null) return '';
  if (typeof v === 'string') return looksLikePath(v) ? basename(v) : v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) return v.map(rawCompact).join(', ');
  try {
    return Object.entries(v as Record<string, unknown>)
      .slice(0, 4)
      .map(([k, val]) => `${k}: ${rawCompact(val)}`)
      .join(' · ');
  } catch {
    return String(v);
  }
}

function looksLikePath(s: string): boolean {
  return /[/\\]/.test(s) && /\.[a-z0-9]{1,6}$|\/$/i.test(s);
}
