import test from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown, parseInline } from '../src/markdownParser.mjs';

const types = (nodes) => nodes.map((n) => n.type);
// Deep-collect every node in the AST (blocks + inline children).
function walk(nodes, out = []) {
  for (const n of nodes) {
    out.push(n);
    if (n.children) walk(n.children, out);
    if (n.blocks) walk(n.blocks, out);
    if (n.items) walk(n.items, out);
    if (n.header) n.header.forEach((c) => walk(c, out));
    if (n.rows) n.rows.forEach((r) => r.forEach((c) => walk(c, out)));
  }
  return out;
}

test('inline: bold, italic, and code parse to their node types', () => {
  assert.deepEqual(types(parseInline('a **b** c')), ['text', 'strong', 'text']);
  assert.deepEqual(types(parseInline('a *b* c')), ['text', 'em', 'text']);
  const code = parseInline('use `x = 1` here');
  assert.equal(code[1].type, 'code');
  assert.equal(code[1].value, 'x = 1');
});

test('inline: markdown links and bare urls become http(s)-only link nodes', () => {
  const link = parseInline('see [docs](https://example.com/x) now');
  assert.equal(link[1].type, 'link');
  assert.equal(link[1].href, 'https://example.com/x');
  const bare = parseInline('go http://a.b/c end');
  assert.equal(bare[1].type, 'link');
  assert.equal(bare[1].href, 'http://a.b/c');
});

test('XSS: raw HTML and non-http link schemes never produce markup/link nodes', () => {
  // Raw HTML has no matching rule → it survives only as text.
  const html = walk(parseMarkdown('<script>alert(1)</script> and <img src=x onerror=alert(2)>'));
  assert.ok(html.every((n) => n.type !== 'link'), 'no link nodes from raw HTML');
  assert.ok(!html.some((n) => n.type === 'html' || n.type === 'raw'), 'no raw/html node type exists');
  const asText = html.filter((n) => n.type === 'text').map((n) => n.value).join('');
  assert.match(asText, /<script>alert\(1\)<\/script>/, 'the script tag is literal text');
  // A javascript: "link" must NOT be treated as a link.
  const js = walk(parseInline('[click](javascript:alert(1))'));
  assert.ok(js.every((n) => n.type !== 'link'), 'javascript: is never a link');
  const data = walk(parseInline('[x](data:text/html,<script>1</script>)'));
  assert.ok(data.every((n) => n.type !== 'link'), 'data: is never a link');
});

test('blocks: fenced code, headings, lists, and GFM tables', () => {
  const code = parseMarkdown('```js\nconst x = 1;\n```');
  assert.equal(code[0].type, 'code');
  assert.equal(code[0].value, 'const x = 1;');

  const h = parseMarkdown('# Title');
  assert.equal(h[0].type, 'heading');
  assert.equal(h[0].level, 3); // # → h3

  const ul = parseMarkdown('- a\n- b');
  assert.equal(ul[0].type, 'ul');
  assert.equal(ul[0].items.length, 2);

  const ol = parseMarkdown('3. a\n4. b');
  assert.equal(ol[0].type, 'ol');
  assert.equal(ol[0].start, 3);

  const table = parseMarkdown('| a | b |\n| --- | --- |\n| 1 | 2 |');
  assert.equal(table[0].type, 'table');
  assert.equal(table[0].header.length, 2);
  assert.equal(table[0].rows.length, 1);
  assert.equal(table[0].rows[0].length, 2);
});

test('fenced code with a non-trivial info string does not hang the parser (P1 regression lock)', () => {
  // These previously wedged parseMarkdown in an infinite loop: the fence opener
  // (/^```(\w*)\s*$/) was narrower than isBlockStart (/^```/), so an info string
  // with punctuation/second token fell through and never advanced `i`.
  const a = parseMarkdown('```c++\nint x = 1;\n```');
  assert.equal(a[0].type, 'code');
  assert.equal(a[0].value, 'int x = 1;');
  const b = parseMarkdown('```json title="x"\n{"a":1}\n```');
  assert.equal(b[0].type, 'code');
  // A mid-stream partial (unclosed fence) must also terminate, not hang.
  const c = parseMarkdown('```c#\npartial');
  assert.equal(c[0].type, 'code');
});

test('a plain paragraph is a single p block with text', () => {
  const p = parseMarkdown('just some prose here');
  assert.equal(p.length, 1);
  assert.equal(p[0].type, 'p');
  assert.equal(p[0].children[0].type, 'text');
});

// Review 2026-11-27: engineering text must survive the inline rules.
const flat = (nodes) => nodes.map((n) => (n.type === 'text' ? n.value : `<${n.type}>`)).join('');

test('spaced asterisks in a formula stay literal (CommonMark flanking)', () => {
  assert.deepEqual(parseInline('ΔP = ρ * g * h'), [{ type: 'text', value: 'ΔP = ρ * g * h' }]);
  assert.deepEqual(parseInline('5 * 3 > 10 * 2'), [{ type: 'text', value: '5 * 3 > 10 * 2' }]);
  assert.deepEqual(parseInline('a ** b ** c'), [{ type: 'text', value: 'a ** b ** c' }]);
  assert.deepEqual(parseInline('x _ y _ z'), [{ type: 'text', value: 'x _ y _ z' }]);
});

test('a dunder name stays literal', () => {
  assert.deepEqual(parseInline('call __init__ first'), [{ type: 'text', value: 'call __init__ first' }]);
  assert.deepEqual(types(parseInline('a __bold words__ b')), ['text', 'strong', 'text']);
});

test('italic nested in bold renders without stray asterisks', () => {
  const nodes = parseInline('**bold *nested* more**');
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].type, 'strong');
  assert.equal(flat(nodes[0].children), 'bold <em> more');
});

test('a link whose URL holds parentheses stays whole', () => {
  const url = 'https://en.wikipedia.org/wiki/Slug_(software)';
  const link = parseInline(`see [slug](${url}) now`);
  assert.equal(link[1].type, 'link');
  assert.equal(link[1].href, url);
  assert.equal(link[2].value, ' now');
  const bare = parseInline(`see ${url} now`);
  assert.equal(bare[1].href, url);
  const wrapped = parseInline('(see https://a.b/c) end');
  assert.equal(wrapped[1].href, 'https://a.b/c');
  assert.equal(wrapped[2].value, ') end');
});

test('triple asterisks make strong around em, with no stray asterisks', () => {
  for (const [src, inner] of [['***x***', 'x'], ['***two words***', 'two words']]) {
    const nodes = parseInline(src);
    assert.equal(nodes.length, 1, src);
    assert.equal(nodes[0].type, 'strong');
    assert.equal(nodes[0].children.length, 1);
    assert.equal(nodes[0].children[0].type, 'em');
    assert.deepEqual(nodes[0].children[0].children, [{ type: 'text', value: inner }]);
  }
  assert.deepEqual(parseInline('ρ * g * h'), [{ type: 'text', value: 'ρ * g * h' }]);
  assert.deepEqual(parseInline('a *** b *** c'), [{ type: 'text', value: 'a *** b *** c' }]);
});

// List item shape: { type:'li', children: Inline[], blocks: nested ul/ol blocks }.
test('an indented list line nests inside its parent item', () => {
  const ul = parseMarkdown('- a\n  - b\n- c');
  assert.equal(ul.length, 1);
  assert.equal(ul[0].type, 'ul');
  assert.equal(ul[0].items.length, 2);
  assert.equal(flat(ul[0].items[0].children), 'a');
  assert.equal(ul[0].items[0].blocks.length, 1);
  assert.equal(ul[0].items[0].blocks[0].type, 'ul');
  assert.equal(flat(ul[0].items[0].blocks[0].items[0].children), 'b');
  assert.deepEqual(ul[0].items[1].blocks, []);

  const ol = parseMarkdown('1. a\n   - b\n2. c');
  assert.equal(ol.length, 1);
  assert.equal(ol[0].type, 'ol');
  assert.equal(ol[0].items.length, 2);
  assert.equal(ol[0].items[0].blocks[0].type, 'ul');
});

test('lists nest three levels deep, ul and ol mixed', () => {
  const b = parseMarkdown('1. one\n   - two\n     1. three\n     2. four\n   - five\n2. six');
  assert.equal(b.length, 1);
  const l1 = b[0];
  assert.equal(l1.type, 'ol');
  assert.equal(l1.items.length, 2);
  const l2 = l1.items[0].blocks[0];
  assert.equal(l2.type, 'ul');
  assert.equal(l2.items.length, 2);
  const l3 = l2.items[0].blocks[0];
  assert.equal(l3.type, 'ol');
  assert.equal(l3.items.length, 2);
  assert.equal(flat(l3.items[1].children), 'four');
});

test('list nesting depth is bounded for pathological input', () => {
  const src = Array.from({ length: 500 }, (_, k) => `${' '.repeat(2 * k)}- item ${k}`).join('\n');
  const b = parseMarkdown(src);
  const depth = (blocks) => Math.max(0, ...blocks.map((x) => 1 + Math.max(0, ...(x.items || []).map((it) => depth(it.blocks)))));
  assert.equal(depth(b), 6);
  assert.equal(walk(b).filter((n) => n.type === 'li').length, 500);
});

test('a list item continuation line still ends the list as a paragraph', () => {
  const b = parseMarkdown('- a\n  - b\nplain text');
  assert.deepEqual(b.map((x) => x.type), ['ul', 'p']);
});
