// Self-contained, dependency-free Markdown parser → a plain-data AST.
// Emits only a fixed allow-list of node types with string leaves, so the React
// renderer never needs raw HTML and LLM output cannot inject markup.
// Links are http(s)-only by construction.
//
// Kept as .mjs (not .ts) so node:test can unit-test parsing directly (the repo's
// test harness is plain node --test with no TS loader); a sibling markdown.d.ts
// gives Markdown.tsx its types.

/** @typedef {{type:'text',value:string}} TextNode */

// A URL may hold one level of balanced parentheses (…/Slug_(software)); a closing
// parenthesis without its opener ends the URL, so "(see https://a.b/c)" keeps its ")".
const URL = String.raw`https?:\/\/(?:[^\s()]|\([^\s()]*\))+`;

// Emphasis follows CommonMark's flanking rule: the opening delimiter is not followed
// by whitespace and the closing one is not preceded by it, so "ρ * g * h" stays literal.
const INLINE_RULES = [
  // inline code — content is literal, never re-parsed
  { re: /`([^`]+)`/, make: (m) => ({ type: 'code', value: m[1] }) },
  // link — ONLY http/https targets match, so javascript:/data: never become links
  { re: new RegExp(String.raw`\[([^\]]+)\]\((${URL})\)`), make: (m) => ({ type: 'link', href: m[2], children: parseInline(m[1]) }) },
  // ***both*** is strong around em
  { re: /\*\*\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*\*\*/, make: (m) => ({ type: 'strong', children: [{ type: 'em', children: parseInline(m[1]) }] }) },
  // bold may hold single-asterisk italics: **bold *nested* more**
  { re: /\*\*(?=\S)((?:[^*]|\*(?!\*))+?)(?<=\S)\*\*/, make: (m) => ({ type: 'strong', children: parseInline(m[1]) }) },
  // __bold__ only between word boundaries, and never a dunder name such as __init__
  { re: /(^|[^_\w])__(?=\S)(?![A-Za-z0-9_]+__(?![_\w]))([^_]+?)(?<=\S)__(?![_\w])/, make: (m) => ({ type: 'strong', children: parseInline(m[2]), lead: m[1] }) },
  { re: /\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*/, make: (m) => ({ type: 'em', children: parseInline(m[1]) }) },
  { re: /(^|[^_\w])_(?=\S)([^_\n]+?)(?<=\S)_(?![_\w])/, make: (m) => ({ type: 'em', children: parseInline(m[2]), lead: m[1] }) },
  // bare autolink
  { re: new RegExp(`(${URL})`), make: (m) => ({ type: 'link', href: m[1], children: [{ type: 'text', value: m[1] }] }) }
];

/** Parse inline markdown into an array of inline nodes. Raw HTML has no matching
 *  rule, so it falls through as a plain text node (rendered as literal text). */
export function parseInline(text) {
  const nodes = [];
  let rest = text;
  let guard = 0;
  while (rest && guard++ < 2000) {
    let best = null;
    for (const rule of INLINE_RULES) {
      const m = rule.re.exec(rest);
      if (m && (best === null || m.index < best.index)) best = { rule, m, index: m.index };
    }
    if (!best) { nodes.push({ type: 'text', value: rest }); rest = ''; break; }
    const node = best.rule.make(best.m);
    // The `_emphasis_` and `__strong__` rules capture a leading boundary char; keep it as text.
    const lead = node.lead || '';
    delete node.lead;
    const before = rest.slice(0, best.index) + lead;
    if (before) nodes.push({ type: 'text', value: before });
    nodes.push(node);
    rest = rest.slice(best.index + best.m[0].length);
  }
  // Never drop the tail if the guard cap was hit on a pathologically long line.
  if (rest) nodes.push({ type: 'text', value: rest });
  return nodes;
}

const isBlockStart = (line) =>
  /^```/.test(line) ||
  /^#{1,6}\s+/.test(line) ||
  /^\s*[-*+]\s+/.test(line) ||
  /^\s*\d+\.\s+/.test(line) ||
  /^>\s?/.test(line);

// One list line: indent width (tab = 4), marker kind, item text.
const LIST_LINE = /^([ \t]*)([-*+]|\d+\.)\s+(.*)$/;
const MAX_LIST_DEPTH = 6;

// Build ul/ol blocks from consecutive list lines. A line indented 2+ columns past the
// list's first line nests under the previous item; past MAX_LIST_DEPTH it stays flat.
function listBlocks(entries, depth) {
  const out = [];
  let k = 0;
  while (k < entries.length) {
    const { indent: base, kind } = entries[k];
    const start = kind === 'ol' ? parseInt(entries[k].marker, 10) : 1;
    const items = [];
    const nests = depth + 1 < MAX_LIST_DEPTH;
    while (k < entries.length) {
      const e = entries[k];
      if (nests && items.length && e.indent >= base + 2) {
        const sub = [];
        while (k < entries.length && entries[k].indent >= base + 2) sub.push(entries[k++]);
        items[items.length - 1].blocks = listBlocks(sub, depth + 1);
      } else if (e.kind === kind) {
        items.push({ type: 'li', children: parseInline(e.text), blocks: [] });
        k++;
      } else break;
    }
    out.push(kind === 'ol' ? { type: 'ol', start, items } : { type: 'ul', items });
  }
  return out;
}

const splitRow = (line) => {
  let s = line.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|')) s = s.slice(0, -1);
  return s.split('|').map((c) => c.trim());
};

/** Parse a Markdown source string into a block-level AST array. */
export function parseMarkdown(src) {
  const lines = String(src == null ? '' : src).replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === '') { i++; continue; }

    // fenced code — the opener must be exactly as broad as isBlockStart's fence
    // rule (any ```-prefixed line), else a fence with an info string it rejects
    // (```c++, ```json title="x") falls through and wedges the paragraph loop.
    if (/^```/.test(line)) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
      i++; // closing fence (if present)
      blocks.push({ type: 'code', value: buf.join('\n') });
      continue;
    }

    // GFM table: header row with a pipe, next line a separator of dashes
    if (line.includes('|') && i + 1 < lines.length && /^[ \t]*\|?[ \t:|-]*-[ \t:|-]*\|?[ \t]*$/.test(lines[i + 1])) {
      const header = splitRow(line);
      i += 2; // header + separator
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push({
        type: 'table',
        header: header.map(parseInline),
        rows: rows.map((r) => r.map(parseInline))
      });
      continue;
    }

    // heading (#→h3 … ######→h6)
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      blocks.push({ type: 'heading', level: Math.min(6, 2 + h[1].length), children: parseInline(h[2]) });
      i++;
      continue;
    }

    // blockquote
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\s?/, '')); i++; }
      blocks.push({ type: 'blockquote', blocks: parseMarkdown(buf.join('\n')) });
      continue;
    }

    // lists (ul/ol, nested by indent)
    if (LIST_LINE.test(line)) {
      const entries = [];
      let m;
      while (i < lines.length && (m = LIST_LINE.exec(lines[i]))) {
        entries.push({ indent: m[1].replace(/\t/g, '    ').length, marker: m[2], kind: /\d/.test(m[2]) ? 'ol' : 'ul', text: m[3] });
        i++;
      }
      blocks.push(...listBlocks(entries, 0));
      continue;
    }

    // paragraph — gather until a blank line or a block start; soft breaks between lines
    const para = [];
    while (i < lines.length && lines[i].trim() !== '' && !isBlockStart(lines[i])) { para.push(lines[i]); i++; }
    if (para.length === 0) {
      // Forward-progress guard: a line looked like a block start but no rule above
      // consumed it. Emit it as plain text so `i` always advances — never wedge.
      blocks.push({ type: 'p', children: parseInline(line) });
      i++;
      continue;
    }
    const children = [];
    para.forEach((p, idx) => {
      if (idx > 0) children.push({ type: 'break' });
      for (const n of parseInline(p)) children.push(n);
    });
    blocks.push({ type: 'p', children });
  }
  return blocks;
}
