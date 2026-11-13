import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (p) => readFile(new URL(p, import.meta.url), 'utf8');

// The prompt glyph is the same smooth drawing in three places: the in-app
// BrandMark and the two logo sources. Pin the geometry that makes it a `>_`
// plus a block cursor so the copies cannot drift apart.
const CHEVRON = 'M3.5 4.5 7 8l-3.5 3.5';
const UNDERSCORE = /M8\.5 11\.5h3/;
const CURSOR = /<rect x="12" y="4" width="2" height="8" rx="1"/;

test('in-app BrandMark draws a smooth prompt glyph, themed by tokens', async () => {
  const src = await read('../src/BrandMark.tsx');
  assert.ok(src.includes(CHEVRON), 'chevron path matches assets/logo/mark.svg');
  assert.match(src, UNDERSCORE, 'underscore stroke');
  assert.match(src, CURSOR, 'rounded block cursor rect');
  assert.match(src, /viewBox="0 0 16 16"/, '16-unit grid');
  assert.match(src, /strokeLinecap="round"/, 'round caps, never stepped');
  assert.match(src, /strokeLinejoin="round"/, 'round joins, never stepped');
  assert.doesNotMatch(src, /crispEdges/, 'no stepped rendering');
  assert.match(src, /var\(--accent, #7aa2f7\)/, 'prompt follows the accent token');
  assert.match(src, /var\(--accent-2, #9ece6a\)/, 'cursor follows the second accent token');
  assert.match(src, /\{ className \}: \{ className\?: string \}/, 'props are unchanged');
});

test('in-app BrandMark stays decorative and carries no gradient, glow, blur or pixel steps', async () => {
  const src = await read('../src/BrandMark.tsx');
  assert.match(src, /aria-hidden="true"/, 'hidden from assistive tech; the wordmark button names it');
  assert.match(src, /focusable="false"/, 'not a tab stop in legacy engines');
  assert.doesNotMatch(src, /linearGradient|radialGradient|filter|feGaussianBlur|blur|<text|useId|clipPath|mask|crispEdges/);
  assert.doesNotMatch(src, /oc-bore|oc-gas|<circle/, 'the old two-phase pipe mark is gone');
});

test('logo sources carry the same smooth glyph and the Terminalcore palette', async () => {
  const mark = await read('../../assets/logo/mark.svg');
  const tile = await read('../../assets/logo/mark-tile.svg');
  const favicon = await read('../public/favicon.svg');
  for (const [name, svg] of [['mark.svg', mark], ['mark-tile.svg', tile], ['favicon.svg', favicon]]) {
    assert.ok(svg.includes(CHEVRON), `${name} chevron`);
    assert.match(svg, UNDERSCORE, `${name} underscore`);
    assert.match(svg, CURSOR, `${name} cursor`);
    assert.match(svg, /#7aa2f7/, `${name} blue prompt`);
    assert.match(svg, /#9ece6a/, `${name} green cursor`);
    assert.match(svg, /stroke-linecap="round"/, `${name} round caps`);
    assert.doesNotMatch(svg, /crispEdges/, `${name} no stepped rendering`);
    const body = svg.replace(/<!--[\s\S]*?-->/g, '');
    assert.doesNotMatch(body, /Gradient|filter|blur|<text|<circle|mask|clip/i, `${name} stays flat and smooth`);
  }
  assert.match(mark, /role="img" aria-label="OLGA Companion"/, 'standalone mark keeps its accessible name');
  assert.match(tile, /fill="#16161e"/, 'mark-tile.svg night canvas');
  assert.match(tile, /fill="#3b4261"/, 'mark-tile.svg 1-unit line frame');
  assert.match(tile, /<rect width="16" height="16"/, 'mark-tile.svg full-bleed square tile');
});
