/**
 * Render the installer art (NSIS + WiX) from HTML into exact-size PNGs, then to 24-bit BMP.
 *
 *   NODE_PATH=<dir with playwright> node assets/installer/render.mjs
 *   uv run python assets/installer/to_bmp.py
 *
 * Build-time art tooling only; playwright is not an app dependency.
 */
import { chromium } from 'playwright';
import { readFileSync, mkdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '../..');
const out = resolve(here, 'png');
mkdirSync(out, { recursive: true });
const font = (f) => 'data:font/woff2;base64,' + readFileSync(resolve(root, 'frontend/public/fonts', f)).toString('base64');
const mark = (size) => `<svg viewBox="0 0 16 16" width="${size}" height="${size}" aria-hidden="true"><g fill="none" stroke="#7aa2f7" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 4.5 7 8l-3.5 3.5"/><path d="M8.5 11.5h3"/></g><rect x="12" y="4" width="2" height="8" rx="1" fill="#9ece6a"/></svg>`;
const base = `
@font-face { font-family: Meslo; src: url(${font('MesloLGSNF-Bold.woff2')}); font-weight: 700; }
@font-face { font-family: Meslo; src: url(${font('MesloLGSNF-Regular.woff2')}); font-weight: 400; }
@font-face { font-family: Pretendard; src: url(${font('PretendardVariable.woff2')}); font-weight: 100 900; }
* { margin: 0; box-sizing: border-box; }
html, body { overflow: hidden; -webkit-font-smoothing: antialiased; }
.night { background: #16161e; color: #c0caf5; }
.grid { background-image: linear-gradient(#1f2335 1px, transparent 1px), linear-gradient(90deg, #1f2335 1px, transparent 1px); background-size: 12px 12px; }
.word { font-family: Meslo, monospace; font-weight: 700; letter-spacing: .04em; color: #c0caf5; }
.sub { font-family: Meslo, monospace; font-weight: 400; letter-spacing: .22em; color: #7aa2f7; }
.note { font-family: Pretendard, sans-serif; color: #a9b1d6; }
`;
const art = {
  // NSIS welcome/finish sidebar, 164x314.
  'nsis-sidebar': [164, 314, `<body class="night grid" style="width:164px;height:314px;position:relative">
    <div style="position:absolute;left:0;top:0;width:4px;height:314px;background:#7aa2f7"></div>
    <div style="position:absolute;left:22px;top:30px;width:64px;height:64px;background:#1a1b26;border:1px solid #2f3549;display:grid;place-items:center">${mark(44)}</div>
    <div class="word" style="position:absolute;left:22px;top:112px;font-size:26px">OLGA</div>
    <div class="sub" style="position:absolute;left:23px;top:145px;font-size:10px">COMPANION</div>
    <div style="position:absolute;left:22px;top:170px;width:28px;height:3px;background:#9ece6a"></div>
    <div class="note" style="position:absolute;left:22px;right:14px;top:188px;font-size:11px;line-height:1.55">Plan, check and run OLGA cases from a chat.</div>
    <div class="sub" style="position:absolute;left:22px;bottom:18px;font-size:8px;letter-spacing:.12em;color:#565f89">&gt;_ every step approved</div>
  </body>`],
  // NSIS page header image, 150x57 (right side of the header band).
  'nsis-header': [150, 57, `<body class="night" style="width:150px;height:57px;position:relative">
    <div style="position:absolute;left:0;top:0;width:3px;height:57px;background:#7aa2f7"></div>
    <div style="position:absolute;left:14px;top:12px">${mark(32)}</div>
    <div class="word" style="position:absolute;left:54px;top:14px;font-size:15px">OLGA</div>
    <div class="sub" style="position:absolute;left:55px;top:33px;font-size:8px">COMPANION</div>
  </body>`],
  // WiX top banner, 493x58; the dialog draws black title text over the left part.
  'wix-banner': [493, 58, `<body style="width:493px;height:58px;position:relative;background:#f5f6fa">
    <div style="position:absolute;left:0;right:0;bottom:0;height:2px;background:#7aa2f7"></div>
    <div class="night grid" style="position:absolute;right:0;top:0;width:150px;height:56px">
      <div style="position:absolute;left:14px;top:12px">${mark(32)}</div>
      <div class="word" style="position:absolute;left:54px;top:13px;font-size:15px">OLGA</div>
      <div class="sub" style="position:absolute;left:55px;top:32px;font-size:8px">COMPANION</div>
    </div>
  </body>`],
  // WiX welcome/finish background, 493x312; dialog text sits on the right part.
  'wix-dialog': [493, 312, `<body style="width:493px;height:312px;position:relative;background:#ffffff">
    <div class="night grid" style="position:absolute;left:0;top:0;width:164px;height:312px">
      <div style="position:absolute;left:0;top:0;width:4px;height:312px;background:#7aa2f7"></div>
      <div style="position:absolute;left:22px;top:30px;width:64px;height:64px;background:#1a1b26;border:1px solid #2f3549;display:grid;place-items:center">${mark(44)}</div>
      <div class="word" style="position:absolute;left:22px;top:112px;font-size:26px">OLGA</div>
      <div class="sub" style="position:absolute;left:23px;top:145px;font-size:10px">COMPANION</div>
      <div style="position:absolute;left:22px;top:170px;width:28px;height:3px;background:#9ece6a"></div>
      <div class="note" style="position:absolute;left:22px;right:14px;top:188px;font-size:11px;line-height:1.55">Plan, check and run OLGA cases from a chat.</div>
      <div class="sub" style="position:absolute;left:22px;bottom:18px;font-size:8px;letter-spacing:.12em;color:#565f89">&gt;_ every step approved</div>
    </div>
  </body>`],
};

const browser = await chromium.launch();
for (const [name, [w, h, body]] of Object.entries(art)) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>${base}</style></head>${body}</html>`);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: resolve(out, `${name}.png`), clip: { x: 0, y: 0, width: w, height: h } });
  await page.close();
  console.log(`${name}.png ${w}x${h}`);
}
await browser.close();
