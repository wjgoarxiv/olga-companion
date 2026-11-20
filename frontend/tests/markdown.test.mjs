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
    if (n.items) n.items.forEach((it) => walk(it, out));
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
