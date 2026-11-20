/**
 * Rasterize an SVG in this directory to PNG at a given size.
 *
 *   node assets/logo/render.mjs mark-tile.svg 1024 icon-1024.png
 *
 * Uses the installed Edge via Playwright so no rasteriser or browser download is
 * needed. ImageMagick is not used here: without a librsvg delegate it silently
 * renders SVG masks and clip-paths wrong, which is exactly what this mark relies
 * on for the gas void.
 */
// Requires `playwright` to be resolvable from wherever this script is run.
// It is intentionally not a dependency of the app: this is build-time art
// tooling, and the shipped dependency tree stays free of it.
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const [source, sizeArg, out, color] = process.argv.slice(2);
const size = Number(sizeArg);

if (!source || !Number.isFinite(size) || !out) {
  console.error('usage: node render.mjs <source.svg> <size> <out.png>');
  process.exit(1);
}

const svg = readFileSync(resolve(source), 'utf8');
const browser = await chromium.launch({ channel: 'msedge' });
const page = await browser.newPage({ viewport: { width: size, height: size } });

await page.setContent(
  `<style>html,body{margin:0;padding:0;background:transparent;color:${color ?? '#111111'}}
   svg{display:block;width:${size}px;height:${size}px}</style>${svg}`,
);
await page.waitForTimeout(250);
await page.locator('svg').screenshot({ path: resolve(out), omitBackground: true });
await browser.close();

console.log(`${out} ${size}x${size}`);
