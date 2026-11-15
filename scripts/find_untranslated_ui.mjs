// Find UI strings in frontend/src that are not routed through t().
// Covers frontend/src/**/*.tsx (JSX text and visible attributes) plus the
// non-JSX data mode: frontend/src/**/*.ts and *.mjs (skips *.d.ts, *.d.mts,
// frontend/src/i18n/**).
//
// What it flags:
//   - JSX text nodes with letters, e.g. <span>???</span> (skips {expressions}
//     such as {t('chat.retry')}, which live inside braces and are never text)
//   - literal user-visible attributes: placeholder, title, aria-label, alt,
//     label — e.g. title="..." (skips title={t(...)} for the same reason)
//   - data-mode string literals holding Hangul or an English sentence
//     (two or more words), e.g. '안녕' or "save failed, retry" — the kind of
//     copy a .ts/.mjs data module returns to the UI
//
// What it never flags:
//   - strings inside {expressions} (tsx mode), comments, imports, or regex literals
//   - single-word codes, units, file extensions, or search-index tokens
//   - a literal that is the right side of ?? — the codebase routes UI copy as
//     t('key') ?? 'fallback', so the fallback is already keyed, not unrouted
//   - files outside frontend/src, or (data mode) *.d.ts, *.d.mts, i18n/**
//
// Data-mode finding text: quoted literals report their inner value; template
// literals report the full raw slice (backticks and ${...} included) so the
// allow-list can match them exactly. A template is flagged only when its
// static text (outside ${...}) holds Hangul or spaced wording, so pure
// code templates (URL paths, dotted key builders, `key: value` formatting,
// truncation slices, plural-key builders) stay quiet while real copy —
// including single-sentence throws like `Invalid ${field}.` — is reported.
//
// Raw-key pass (scanRawKeyFallbacks, tsx + data files): dynamic UI copy the
// literal scanners cannot see —
//   - `<callee>.replaceAll('_', ' ')`: a wire key prettified into a label or
//     sentence at render time (e.g. a run_patrol metric dt). Route the label
//     through t() instead; audit receipts that intentionally show raw wire
//     keys are allow-listed per callee with a reason.
//   - `return 'unavailable'`: a raw English fallback rendered where a value is
//     missing. Route it through t() instead.
// The finding text is the normalized snippet (`key.replaceAll('_', ' ')`,
// `return 'unavailable'`), so the allow-list matches per callee.
//
// Allow-list file (default frontend/i18n-allowlist.json):
//   { "allow": ["OLGA", "/\\bPT\\b/", ".genkey"] }
//   A finding is allow-listed only when NOTHING translatable remains after
//   removing every entry: plain strings are cut out (case-sensitive), while
//   "/pattern/flags" entries are removed as global regex matches. So "OLGA"
//   alone is allow-listed, but "Return to OLGA home" still needs translation
//   (OLGA stays as-is in both languages). Single letters must use boundary
//   regexes ("/\\bm\\b/"), never plain strings.
//   Rationale: identifiers, units, file extensions and brand names never
//   translate, but a sentence containing them still does.
//
// Exit code: 0 when every finding is allow-listed, 1 otherwise.
// Output: one "file:line: [translate|allow-listed] text" line per finding.
import { readdir, readFile } from 'node:fs/promises';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..');
const DEFAULT_ROOT = join(REPO, 'frontend', 'src');
const DEFAULT_ALLOWLIST = join(REPO, 'frontend', 'i18n-allowlist.json');

export const VISIBLE_ATTRS = new Set([
  'placeholder',
  'title',
  'aria-label',
  'ariaLabel',
  'alt',
  'label',
  'kicker',
  'description',
  'hint',
  'error',
  'badge',
  'contextLabel',
  'contextValue',
  'contextDetail',
]);
const HAS_LETTER = /\p{L}/u;
const HAS_HANGUL = /[가-힣]/;
const HAS_SPACE = /\s/;
const HAS_CAP_WORD = /\b[A-Z][a-z]{2,}/;
const HAS_COPY = (value) => HAS_HANGUL.test(value) || HAS_CAP_WORD.test(value)
  || (HAS_LETTER.test(value) && HAS_SPACE.test(value));

const BARE_CODE_WORDS = new Set(['instanceof', 'new', 'extends', 'throw', 'class', 'from', 'import']);
const CALL_CODE_WORDS = new Set(['require', 't', 'text', 'translate']);

function isCodePositionLiteral(src, index) {
  // Module specifiers, error/class identities and i18n key arguments are
  // code, never visible copy: import x from './ui/Button',
  // error instanceof AbortError, new TypeError('...'), t('ns.key').
  // The index sits on the literal's opening quote: for call forms the char
  // before the literal is '(' and the word before that is the callee.
  const before = prevSignificant(src, index);
  if (before >= 0 && src[before] === '(') {
    if (CALL_CODE_WORDS.has(precedingWord(src, before))) return true;
  }
  return BARE_CODE_WORDS.has(precedingWord(src, index));
}

function parseArgs(argv) {
  const opts = { root: DEFAULT_ROOT, allowlist: DEFAULT_ALLOWLIST };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--root') opts.root = resolve(argv[i + 1]);
    if (argv[i] === '--allowlist') opts.allowlist = resolve(argv[i + 1]);
  }
  return opts;
}

export function loadAllowlist(path) {
  if (!existsSync(path)) return [];
  try {
    const raw = JSON.parse(readFileSync(path, 'utf8'));
    if (Array.isArray(raw?.allow)) return raw.allow.filter((e) => typeof e === 'string');
  } catch {
    // A broken allow-list must not hide findings; treat as empty.
  }
  return [];
}

function toRegExp(entry) {
  const end = entry.lastIndexOf('/');
  if (entry.length < 2 || !entry.startsWith('/') || end <= 0) return null;
  try {
    return new RegExp(entry.slice(1, end), entry.slice(end + 1).includes('g') ? entry.slice(end + 1) : `${entry.slice(end + 1)}g`);
  } catch {
    return null; // Invalid regex entry: ignore it rather than crashing the sweep.
  }
}

export function stripAllowlisted(text, entries) {
  let out = text;
  const ordered = [...entries].sort((a, b) => b.length - a.length);
  for (const entry of ordered) {
    if (entry === '') continue;
    const pattern = toRegExp(entry);
    if (pattern) {
      out = out.replace(pattern, '');
    } else {
      out = out.split(entry).join('');
    }
  }
  return out;
}

export function isAllowListed(text, entries) {
  return !HAS_LETTER.test(stripAllowlisted(text, entries));
}

async function collectTsx(dir, out) {
  for (const name of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, name.name);
    if (name.isDirectory()) await collectTsx(full, out);
    else if (name.isFile() && full.endsWith('.tsx')) out.push(full);
  }
  return out;
}

async function collectData(dir, out) {
  for (const name of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, name.name);
    if (name.isDirectory()) {
      if (name.name === 'i18n') continue;
      await collectData(full, out);
    } else if (name.isFile()) {
      if (full.endsWith('.mjs')) out.push(full);
      else if (full.endsWith('.ts') && !full.endsWith('.d.ts') && !full.endsWith('.d.mts')) out.push(full);
    }
  }
  return out;
}

function isNullishFallback(src, index) {
  // A literal routed as t('key') ?? 'fallback' is already keyed: the literal
  // is only the no-t safety net, never untranslated UI copy. Only a t(),
  // text() or translate() call on the left earns the exemption — any other
  // producer (foo ?? 'words') still reports the literal.
  const p = prevSignificant(src, index);
  if (!(p >= 1 && src[p] === '?' && src[p - 1] === '?')) return false;
  return nullishCallee(src, p - 1) !== null;
}

function nullishCallee(src, index) {
  // Index sits just before the '??'. When the left side ends in a call,
  // returns its callee name (t, text, translate or null).
  let j = prevSignificant(src, index);
  if (j < 0 || src[j] !== ')') return null;
  let depth = 0;
  while (j >= 0) {
    const ch = src[j];
    if (ch === '"' || ch === "'") {
      // Skip a quoted span backwards (honors backslash escapes).
      let k = j - 1;
      let escapes = 0;
      while (k >= 0 && src[k] === '\\') {
        escapes += 1;
        k -= 1;
      }
      if (escapes % 2 === 0) {
        const quote = ch;
        j -= 1;
        while (j >= 0 && src[j] !== quote) {
          if (src[j] === '\\') j -= 1;
          j -= 1;
        }
        j -= 1;
        continue;
      }
      j -= 1;
      continue;
    }
    if (ch === '`') return null; // template on the left: stay loud, not sorry.
    if (ch === ')') depth += 1;
    else if (ch === '(') {
      depth -= 1;
      if (depth === 0) break;
    }
    j -= 1;
  }
  if (j < 0) return null;
  let k = j - 1;
  while (k >= 0 && (src[k] === '?' || src[k] === '.' || src[k] === ' ' || src[k] === '\t' || src[k] === '\n' || src[k] === '\r')) k -= 1;
  let name = '';
  while (k >= 0 && /[A-Za-z_$]/.test(src[k])) {
    name = src[k] + name;
    k -= 1;
  }
  return name === 't' || name === 'text' || name === 'translate' ? name : null;
}

function readTemplate(src, index) {
  // Returns { raw, end } for a `...` literal starting at index, or null.
  // Tracks ${...} nesting so braces and quotes inside expressions cannot
  // end the literal early.
  let i = index + 1;
  let depth = 0;
  while (i < src.length) {
    const ch = src[i];
    if (ch === '\\') {
      i += 2;
      continue;
    }
    if (ch === '`') {
      if (depth === 0) return { raw: src.slice(index, i + 1), end: i + 1 };
      const nested = readTemplate(src, i);
      if (!nested) return null;
      i = nested.end;
      continue;
    }
    if (ch === '$' && src[i + 1] === '{') {
      depth += 1;
      i += 2;
      continue;
    }
    if (ch === '}' && depth > 0) {
      depth -= 1;
      i += 1;
      continue;
    }
    if (depth > 0 && (ch === '"' || ch === "'")) {
      const lit = readString(src, i);
      i = lit ? lit.end : i + 1;
      continue;
    }
    if (depth > 0 && ch === '/' && (src[i + 1] === '/' || src[i + 1] === '*')) {
      if (src[i + 1] === '/') {
        while (i < src.length && src[i] !== '\n') i += 1;
      } else {
        const end = src.indexOf('*/', i + 2);
        i = end < 0 ? src.length : end + 2;
      }
      continue;
    }
    i += 1;
  }
  return null;
}

export function templateStaticText(raw) {
  // Static text of a template raw slice: ${...} spans removed so only the
  // author's own wording is judged. Honors escapes, nested ${...}, quotes
  // and comments inside expressions, and nested templates.
  let out = '';
  let i = 1; // skip the opening backtick
  const end = raw.length - 1; // skip the closing backtick
  while (i < end) {
    const ch = raw[i];
    if (ch === '\\') {
      i += 2;
      continue;
    }
    if (ch === '$' && raw[i + 1] === '{') {
      let depth = 1;
      i += 2;
      while (i < end && depth > 0) {
        const c = raw[i];
        if (c === '\\') {
          i += 2;
          continue;
        }
        if (c === '"' || c === "'") {
          const lit = readString(raw, i);
          i = lit ? lit.end : i + 1;
          continue;
        }
        if (c === '`') {
          const nested = readTemplate(raw, i);
          i = nested ? nested.end : i + 1;
          continue;
        }
        if (c === '/' && raw[i + 1] === '/') {
          while (i < end && raw[i] !== '\n') i += 1;
          continue;
        }
        if (c === '/' && raw[i + 1] === '*') {
          const stop = raw.indexOf('*/', i + 2);
          i = stop < 0 || stop + 2 > end ? end : stop + 2;
          continue;
        }
        if (c === '$' && raw[i + 1] === '{') depth += 1;
        else if (c === '}') depth -= 1;
        i += 1;
      }
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}

const REGEX_KEYWORDS = new Set(['return', 'typeof', 'in', 'of', 'new', 'delete', 'void', 'instanceof', 'do', 'else', 'case', 'throw']);

function looksLikeRegex(src, index) {
  // A "/" starts a regex unless it reads as division: preceded by a value
  // (word char, ), ]) and not by a keyword like "return".
  const p = prevSignificant(src, index);
  if (p < 0) return true;
  const ch = src[p];
  if (!/[A-Za-z0-9_$)\]]/.test(ch)) return true;
  return REGEX_KEYWORDS.has(precedingWord(src, index));
}

function readRegex(src, index) {
  // Index sits on the opening "/"; returns the end offset or null.
  let i = index + 1;
  let inClass = false;
  while (i < src.length) {
    const ch = src[i];
    if (ch === '\\') {
      i += 2;
      continue;
    }
    if (ch === '\n') return null;
    if (ch === '[') inClass = true;
    else if (ch === ']' && inClass) inClass = false;
    else if (ch === '/' && !inClass) {
      i += 1;
      while (i < src.length && /[a-z]/i.test(src[i])) i += 1;
      return i;
    }
    i += 1;
  }
  return null;
}

export function scanDataSource(src) {
  // Findings: [{ line, kind: 'data', attr: null, text }]. A separate,
  // non-JSX pass: plain .ts/.mjs has no tags, so generics and "<"
  // comparisons must never read as markup — only string literals are
  // examined, one literal at a time.
  const findings = [];
  let line = 1;
  const countLines = (from, to) => {
    for (let i = from; i < to; i += 1) if (src[i] === '\n') line += 1;
  };
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    if (ch === '\n') {
      line += 1;
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      const lit = readString(src, i);
      if (!lit) {
        i += 1;
        continue;
      }
      const startLine = line;
      countLines(i, lit.end);
      if (!isNullishFallback(src, i) && !isCodePositionLiteral(src, i) && HAS_LETTER.test(lit.value) && HAS_COPY(lit.value)) {
        findings.push({ line: startLine, kind: 'data', attr: null, text: lit.value });
      }
      i = lit.end;
      continue;
    }
    if (ch === '`') {
      const tpl = readTemplate(src, i);
      if (!tpl) {
        i += 1;
        continue;
      }
      const startLine = line;
      countLines(i, tpl.end);
      const stat = templateStaticText(tpl.raw);
      if (!isNullishFallback(src, i) && !isCodePositionLiteral(src, i) && HAS_COPY(stat)) {
        findings.push({ line: startLine, kind: 'data', attr: null, text: tpl.raw });
      }
      i = tpl.end;
      continue;
    }
    if (ch === '/' && src[i + 1] === '/') {
      while (i < src.length && src[i] !== '\n') i += 1;
      continue;
    }
    if (ch === '/' && src[i + 1] === '*') {
      const end = src.indexOf('*/', i + 2);
      const stop = end < 0 ? src.length : end + 2;
      countLines(i, stop);
      i = stop;
      continue;
    }
    if (ch === '/') {
      if (looksLikeRegex(src, i)) {
        const end = readRegex(src, i);
        if (end) {
          countLines(i, end);
          i = end;
          continue;
        }
      }
      i += 1;
      continue;
    }
    i += 1;
  }
  return findings;
}

function prevSignificant(src, index) {
  let i = index - 1;
  while (i >= 0 && (src[i] === ' ' || src[i] === '\t' || src[i] === '\n' || src[i] === '\r')) i -= 1;
  return i;
}

function precedingWord(src, index) {
  let i = prevSignificant(src, index);
  let word = '';
  while (i >= 0 && /[A-Za-z_$]/.test(src[i])) {
    word = src[i] + word;
    i -= 1;
  }
  return word;
}

function jsxTagOpener(src, index) {
  // True when "<" starts a JSX element: <Name, </, or <>.
  const next = src[index + 1];
  if (next === '>' || (next === '/' && /[A-Za-z>]/.test(src[index + 2] ?? ''))) {
    // Fragment <> or closing </... — always structural.
    if (next === '>') return 'open';
    return 'close';
  }
  if (!next || !/[A-Za-z]/.test(next)) return null;
  const p = prevSignificant(src, index);
  if (p < 0) return 'open';
  const ch = src[p];
  if ('>({[=,:;?&|}'.includes(ch) || ch === ')') return 'open';
  if (precedingWord(src, index) === 'return') return 'open';
  return null;
}

function readString(src, index) {
  // Returns { value, end } for a '...' or "..." literal starting at index.
  const quote = src[index];
  let out = '';
  let i = index + 1;
  while (i < src.length) {
    const ch = src[i];
    if (ch === '\\') {
      out += src.slice(i, i + 2);
      i += 2;
      continue;
    }
    if (ch === quote) return { value: out, end: i + 1 };
    if (ch === '\n') break; // Unterminated: not a real string.
    out += ch;
    i += 1;
  }
  return null;
}

function attrNameBefore(src, index) {
  const p = prevSignificant(src, index);
  if (p < 0 || src[p] !== '=') return null;
  let i = p - 1;
  while (i >= 0 && (src[i] === ' ' || src[i] === '\t')) i -= 1;
  let name = '';
  while (i >= 0 && /[A-Za-z-]/.test(src[i])) {
    name = src[i] + name;
    i -= 1;
  }
  return name || null;
}

export function scanSource(src) {
  // Findings: [{ line, kind: 'text'|'attr'|'data', attr, text }].
  const findings = [];
  let line = 1;
  let braceDepth = 0;
  let tagDepth = 0;
  let inTag = false;
  const tagStack = []; // entries {open:boolean, saved:number, expr:number} for nested elements
  // Expression levels are tracked per tag: entering an element saves the
  // enclosing jsxExpr and restarts at 0, so text and attributes inside
  // {cond && (<X …/>)} containers are still scanned. Leaving the element
  // restores the enclosing level.
  const pushTag = (entry) => {
    tagStack.push({ ...entry, expr: jsxExpr });
    jsxExpr = 0;
  };
  const popTag = () => {
    const popped = tagStack.pop();
    if (popped && typeof popped.expr === 'number') jsxExpr = popped.expr;
    return popped;
  };
  // Attribute-expression visibility: title={…} counts as visible copy when
  // the attribute itself is user-visible, so its quoted branches are scanned.
  const attrExprStack = []; // attr names (or null) for nested {…} inside tags
  const topAttrVisible = () => {
    const top = attrExprStack[attrExprStack.length - 1];
    return top !== null && top !== undefined && VISIBLE_ATTRS.has(top);
  };
  const isQuoteDataEligible = () => tagDepth === 0
    || (!inTag && jsxExpr > 0)
    || (inTag && tagBraces > 0 && topAttrVisible());
  const isTemplateDataEligible = (pos) => tagDepth === 0
    || (!inTag && jsxExpr > 0)
    || (inTag && tagBraces > 0 && topAttrVisible())
    || (inTag && tagBraces === 0 && jsxExpr === 0 && VISIBLE_ATTRS.has(attrNameBefore(src, pos) ?? ''));
  // Template literals: stack of { braceLevel } to resume after ${...}.
  const tmplStack = [];
  let inTemplate = false;

  const countLines = (from, to) => {
    for (let i = from; i < to; i += 1) if (src[i] === '\n') line += 1;
  };

  let i = 0;
  let tagBraces = 0; // "{" depth inside the current open tag (attribute expressions)
  let jsxExpr = 0; // "{" depth inside JSX children (t(...) calls live here)
  while (i < src.length) {
    const ch = src[i];

    if (inTemplate) {
      if (ch === '\\') {
        i += 2;
        continue;
      }
      if (ch === '`') {
        inTemplate = false;
        i += 1;
        continue;
      }
      if (ch === '\n') line += 1;
      if (ch === '$' && src[i + 1] === '{') {
        tmplStack.push({ braceLevel: braceDepth });
        braceDepth += 1;
        inTemplate = false;
        i += 2;
        continue;
      }
      i += 1;
      continue;
    }

    if (ch === '\n') {
      line += 1;
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      const lit = readString(src, i);
      if (lit) {
        countLines(i, lit.end);
        if (inTag && tagBraces === 0 && jsxExpr === 0 && tagDepth > 0) {
          const name = attrNameBefore(src, i);
          if (name && VISIBLE_ATTRS.has(name) && HAS_LETTER.test(lit.value)) {
            findings.push({ line, kind: 'attr', attr: name, text: lit.value });
          }
        } else if (isQuoteDataEligible() && !isNullishFallback(src, i) && !isCodePositionLiteral(src, i)
          && HAS_LETTER.test(lit.value) && HAS_COPY(lit.value)) {
          // Script and expression literals (module consts, ternary branches,
          // visible-attr expressions): same copy rules as the .ts/.mjs mode.
          findings.push({ line, kind: 'data', attr: null, text: lit.value });
        }
        i = lit.end;
        continue;
      }
      i += 1;
      continue;
    }
    if (ch === '`') {
      if (isTemplateDataEligible(i)) {
        const tpl = readTemplate(src, i);
        if (tpl) {
          const startLine = line;
          countLines(i, tpl.end);
          const stat = templateStaticText(tpl.raw);
          if (!isNullishFallback(src, i) && !isCodePositionLiteral(src, i) && HAS_COPY(stat)) {
            findings.push({ line: startLine, kind: 'data', attr: null, text: tpl.raw });
          }
          i = tpl.end;
          continue;
        }
      }
      inTemplate = true;
      i += 1;
      continue;
    }
    if (ch === '/' && src[i + 1] === '/' && !(tagDepth > 0 && !inTag && jsxExpr === 0)) {
      while (i < src.length && src[i] !== '\n') i += 1;
      continue;
    }
    if (ch === '/' && src[i + 1] === '*' && !(tagDepth > 0 && !inTag && jsxExpr === 0)) {
      const end = src.indexOf('*/', i + 2);
      const stop = end < 0 ? src.length : end + 2;
      countLines(i, stop);
      i = stop;
      continue;
    }
    if (ch === '{') {
      braceDepth += 1;
      if (inTag) {
        if (tagBraces === 0) attrExprStack.push(attrNameBefore(src, i));
        tagBraces += 1;
      }
      // Template ${...} pairs are tracked by tmplStack/braceDepth; only
      // real JSX expression braces move jsxExpr.
      else if (tagDepth > 0 && tmplStack.length === 0) jsxExpr += 1;
      i += 1;
      continue;
    }
    if (ch === '}') {
      if (braceDepth > 0) braceDepth -= 1;
      if (inTag && tagBraces > 0) {
        if (tagBraces === 1) attrExprStack.pop();
        tagBraces -= 1;
      }
      else if (!inTag && tagDepth > 0 && jsxExpr > 0 && tmplStack.length === 0) jsxExpr -= 1;
      const top = tmplStack[tmplStack.length - 1];
      if (top && braceDepth === top.braceLevel) {
        tmplStack.pop();
        inTemplate = true;
      }
      i += 1;
      continue;
    }
    if (ch === '<') {
      const kind = jsxTagOpener(src, i);
      if (kind === 'open') {
        if (src[i + 1] === '>') {
          pushTag({ open: false, saved: tagBraces });
          tagDepth += 1;
          inTag = false;
          i += 2; // "<>" fragment: no attributes possible.
          continue;
        }
        pushTag({ open: true, saved: tagBraces });
        tagDepth += 1;
        inTag = true;
        tagBraces = 0;
        i += 1;
        continue;
      }
      if (kind === 'close') {
        // Consume to the matching ">" so attribute braces cannot confuse us.
        let depth = 0;
        let j = i + 2;
        while (j < src.length) {
          const c = src[j];
          if (c === '\n') line += 1;
          if (c === '"' || c === "'") {
            const lit = readString(src, j);
            j = lit ? lit.end : j + 1;
            continue;
          }
          if (c === '{') depth += 1;
          else if (c === '}') depth = Math.max(0, depth - 1);
          else if (c === '>' && depth === 0) {
            j += 1;
            break;
          }
          j += 1;
        }
        popTag();
        tagDepth = Math.max(0, tagDepth - 1);
        tagBraces = 0;
        const parent = tagStack[tagStack.length - 1];
        inTag = !!parent && parent.open;
        i = j;
        continue;
      }
      // A "<" that opens nothing (comparison, or literal text like "a < b"):
      // capture the run; inline elements open real tags for the main loop.
      if (tagDepth > 0 && !inTag && jsxExpr === 0) {
        const startLine = line;
        let j = i;
        let text = '';
        let resumeAt = -1;
        while (j < src.length) {
          if (src[j] === '{' || src[j] === '\n') break;
          if (src[j] === '<') {
            const closer = src.slice(j).match(/^<\/[A-Za-z][\w.-]*\s*>/);
            if (closer) {
              popTag();
              tagDepth = Math.max(0, tagDepth - 1);
              countLines(j, j + closer[0].length);
              j += closer[0].length;
              const into = tagStack[tagStack.length - 1];
              inTag = !!into && into.open;
              // A closer that returns to an expression level or back inside
              // a tag ends the run: what follows is code (}: else-branches,
              // map tails, attribute expressions), not text.
              if (jsxExpr > 0 || inTag) break;
              text += ' ';
              continue;
            }
            const opener = src.slice(j).match(/^<[A-Za-z][\w.-]*(?=[\s/>])/);
            if (opener && j !== i) {
              pushTag({ open: true, saved: tagBraces });
              tagDepth += 1;
              tagBraces = 0;
              inTag = true;
              resumeAt = j + 1;
              break;
            }
            if (opener && j === i) {
              // The "<" we started from failed the preceder check, but it
              // still starts an inline element: open it for the main loop.
              // (A bare "a < b" comparison has a space after "<" and never
              // matches the opener pattern, so it stays literal.)
              pushTag({ open: true, saved: tagBraces });
              tagDepth += 1;
              tagBraces = 0;
              inTag = true;
              resumeAt = j + 1;
              break;
            }
            const selfClosing = src.slice(j).match(/^<[A-Za-z][\w.-]*(?:\s[^<>]*)?\/>/);
            if (selfClosing) {
              countLines(j, j + selfClosing[0].length);
              j += selfClosing[0].length;
              text += ' ';
              continue;
            }
          }
          text += src[j];
          j += 1;
        }
        const clean = text
          .replace(/\s+/g, ' ')
          .trim()
          .replace(/^[;]+|[;]+$/g, '')
          .trim();
        if (clean !== '' && HAS_LETTER.test(clean)) {
          findings.push({ line: startLine, kind: 'text', attr: null, text: clean });
        }
        i = resumeAt >= 0 ? resumeAt : j;
        continue;
      }
      i += 1;
      continue;
    }
    if (ch === '>' && inTag && tagBraces === 0) {
      if (src[i - 1] === '=') {
        i += 1; // "=>" arrow inside an attribute expression.
        continue;
      }
      if (i > 0 && src[i - 1] === '/') {
        popTag(); // self-closing: back to the enclosing context.
        tagDepth = Math.max(0, tagDepth - 1);
        tagBraces = tagStack.length > 0 ? tagStack[tagStack.length - 1].saved : 0;
      } else if (tagStack.length > 0) {
        tagStack[tagStack.length - 1].open = false;
      }
      const top = tagStack[tagStack.length - 1];
      inTag = !!top && top.open;
      i += 1;
      continue;
    }
    if (ch === '=' && src[i + 1] === '>') {
      i += 2; // "=>" outside a tag: never a tag close.
      continue;
    }

    // JSX text node: printable run until the next tag or expression. Inline
    // elements (<code>, <span>, ...) inside the run open real tags so their
    // attributes are still scanned by the main loop.
    if (tagDepth > 0 && !inTag && jsxExpr === 0 && !/\s/.test(ch)) {
      const startLine = line;
      let j = i;
      let text = '';
      let resumeAt = -1;
      while (j < src.length) {
        if (src[j] === '{' || src[j] === '\n') break;
        if (src[j] === '<') {
          const closer = src.slice(j).match(/^<\/[A-Za-z][\w.-]*\s*>/);
          if (closer) {
            popTag();
            tagDepth = Math.max(0, tagDepth - 1);
            countLines(j, j + closer[0].length);
            j += closer[0].length;
            const into = tagStack[tagStack.length - 1];
            inTag = !!into && into.open;
            // A closer that returns to an expression level or back inside
            // a tag ends the run: what follows is code (}: else-branches,
            // map tails, attribute expressions), not text.
            if (jsxExpr > 0 || inTag) break;
            text += ' ';
            continue;
          }
          const opener = src.slice(j).match(/^<[A-Za-z][\w.-]*(?=[\s/>])/);
          if (opener) {
            pushTag({ open: true, saved: tagBraces });
            tagDepth += 1;
            tagBraces = 0;
            inTag = true;
            resumeAt = j + 1; // let the main loop parse the tag itself
            break;
          }
          const selfClosing = src.slice(j).match(/^<[A-Za-z][\w.-]*(?:\s[^<>]*)?\/>/);
          if (selfClosing) {
            countLines(j, j + selfClosing[0].length);
            j += selfClosing[0].length;
            text += ' ';
            continue;
          }
          break;
        }
        text += src[j];
        j += 1;
      }
      const clean = text
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/^[;]+|[;]+$/g, '')
        .trim();
      if (clean !== '' && HAS_LETTER.test(clean)) {
        findings.push({ line: startLine, kind: 'text', attr: null, text: clean });
      }
      i = resumeAt >= 0 ? resumeAt : j;
      continue;
    }
    i += 1;
  }
  findings.endState = {
    tagDepth,
    jsxExpr,
    braceDepth,
    inTag,
    stack: tagStack.length,
    line,
  };
  return findings;
}

const RAW_KEY_LABEL_PATTERN = /([A-Za-z_$][\w$]*)\.replaceAll\(\s*['"]_['"]\s*,\s*['"] ['"]\s*\)/g;
const RAW_UNAVAILABLE_PATTERN = /(^|[^\w$.])return\s*['"]unavailable['"]/;

function lineCommentStart(line) {
  const first = line.indexOf('//');
  if (first < 0) return -1;
  if (line[first - 1] === ':') return line.indexOf('//', first + 2);
  return first;
}

export function scanRawKeyFallbacks(src) {
  // Findings: [{ line, kind: 'raw-key', attr: null, text }]. One finding per
  // line per rule; a match inside a // comment is not code.
  const findings = [];
  const lines = src.split('\n');
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const cut = lineCommentStart(line);
    const code = cut < 0 ? line : line.slice(0, cut);
    const seen = new Set();
    for (const match of code.matchAll(RAW_KEY_LABEL_PATTERN)) {
      const text = `${match[1]}.replaceAll('_', ' ')`;
      if (seen.has(text)) continue;
      seen.add(text);
      findings.push({ line: index + 1, kind: 'raw-key', attr: null, text });
    }
    if (RAW_UNAVAILABLE_PATTERN.test(code)) {
      findings.push({ line: index + 1, kind: 'raw-key', attr: null, text: "return 'unavailable'" });
    }
  }
  return findings;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const allowEntries = loadAllowlist(opts.allowlist);
  if (!existsSync(opts.allowlist)) {
    process.stderr.write(`warning: allow-list not found at ${opts.allowlist}; treating as empty\n`);
  }
  const tsxFiles = await collectTsx(opts.root, []);
  tsxFiles.sort();
  const dataFiles = await collectData(opts.root, []);
  dataFiles.sort();
  let untranslated = 0;
  const reportRawKeys = (file, src) => {
    for (const f of scanRawKeyFallbacks(src)) {
      const listed = isAllowListed(f.text, allowEntries);
      if (!listed) untranslated += 1;
      const rel = file.split('frontend')[1] ? `frontend${file.split('frontend')[1]}` : file;
      process.stdout.write(`${rel}:${f.line}: [${listed ? 'allow-listed' : 'translate'}] [raw-key] ${f.text}\n`);
    }
  };
  for (const file of tsxFiles) {
    const src = await readFile(file, 'utf8');
    for (const f of scanSource(src)) {
      const listed = isAllowListed(f.text, allowEntries);
      if (!listed) untranslated += 1;
      const rel = file.split('frontend')[1] ? `frontend${file.split('frontend')[1]}` : file;
      const extra = f.kind === 'attr' ? ` [${f.attr}]` : '';
      process.stdout.write(`${rel}:${f.line}: [${listed ? 'allow-listed' : 'translate'}]${extra} ${f.text}\n`);
    }
    reportRawKeys(file, src);
  }
  for (const file of dataFiles) {
    const src = await readFile(file, 'utf8');
    for (const f of scanDataSource(src)) {
      const listed = isAllowListed(f.text, allowEntries);
      if (!listed) untranslated += 1;
      const rel = file.split('frontend')[1] ? `frontend${file.split('frontend')[1]}` : file;
      process.stdout.write(`${rel}:${f.line}: [${listed ? 'allow-listed' : 'translate'}] ${f.text}\n`);
    }
    reportRawKeys(file, src);
  }
  process.stderr.write(`${tsxFiles.length} tsx + ${dataFiles.length} data files scanned, ${untranslated} untranslated finding(s)\n`);
  process.exit(untranslated === 0 ? 0 : 1);
}

const invokedDirectly =
  process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) await main();
