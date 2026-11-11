import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (p) => readFile(new URL(p, import.meta.url), 'utf8');

// The prompt glyph is the same drawing in four places. Pin the geometry that
// makes it a `>_` plus a block cursor so the copies cannot drift apart.
const CHEVRON = 'M2 4H4V5H5V6H6V7H7V9H6V10H5V11H4V12H2V11H3V10H4V9H5V7H4V6H3V5H2Z';
const UNDERSCORE = /<rect x="8" y="10" width="3" height="2"/;
const CURSOR = /<rect x="12" y="4" width="2" height="8"/;

test('in-app BrandMark draws the prompt glyph on the shared grid, themed by tokens', async () => {
  const src = await read('../src/BrandMark.tsx');
  assert.ok(src.includes(CHEVRON), 'chevron path matches assets/logo/mark.svg');
  assert.match(src, UNDERSCORE, 'underscore rect');
  assert.match(src, CURSOR, 'block cursor rect');
  assert.match(src, /viewBox="0 0 16 16"/, '16-unit integer grid');
  assert.match(src, /shapeRendering="crispEdges"/, 'no anti-aliased edges at 16 px');
  assert.match(src, /var\(--accent, #7aa2f7\)/, 'prompt follows the accent token');
  assert.match(src, /var\(--accent-2, #9ece6a\)/, 'cursor follows the second accent token');
  assert.match(src, /\{ className \}: \{ className\?: string \}/, 'props are unchanged');
});

test('in-app BrandMark stays decorative and carries no gradient, glow, blur or rounding', async () => {
  const src = await read('../src/BrandMark.tsx');
  assert.match(src, /aria-hidden="true"/, 'hidden from assistive tech; the wordmark button names it');
  assert.match(src, /focusable="false"/, 'not a tab stop in legacy engines');
  assert.doesNotMatch(src, /linearGradient|radialGradient|filter|feGaussianBlur|blur|rx=|ry=|<text|useId|clipPath|mask/);
  assert.doesNotMatch(src, /oc-bore|oc-gas|<circle/, 'the old two-phase pipe mark is gone');
});

test('logo sources and favicon carry the same glyph and the Terminalcore palette', async () => {
  const mark = await read('../../assets/logo/mark.svg');
  const tile = await read('../../assets/logo/mark-tile.svg');
  const fav = await read('../public/favicon.svg');
  for (const [name, svg] of [['mark.svg', mark], ['mark-tile.svg', tile], ['favicon.svg', fav]]) {
    assert.ok(svg.includes(CHEVRON), `${name} chevron`);
    assert.match(svg, UNDERSCORE, `${name} underscore`);
    assert.match(svg, CURSOR, `${name} cursor`);
    assert.match(svg, /#7aa2f7/, `${name} blue prompt`);
    assert.match(svg, /#9ece6a/, `${name} green cursor`);
    assert.match(svg, /shape-rendering="crispEdges"/, `${name} crisp edges`);
    const body = svg.replace(/<!--[\s\S]*?-->/g, '');
    assert.doesNotMatch(body, /Gradient|filter|blur|rx=|<text|<circle|mask|clip/i, `${name} stays flat and square`);
  }
  assert.match(mark, /role="img" aria-label="OLGA Companion"/, 'standalone mark keeps its accessible name');
  for (const [name, svg] of [['mark-tile.svg', tile], ['favicon.svg', fav]]) {
    assert.match(svg, /fill="#16161e"/, `${name} night canvas`);
    assert.match(svg, /fill="#3b4261"/, `${name} 1-unit line frame`);
    assert.match(svg, /<rect width="16" height="16"/, `${name} full-bleed square tile`);
  }
});
