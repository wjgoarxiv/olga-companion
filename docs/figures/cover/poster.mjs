// Static README posters. Tokyo Night, square frames, no glow.
// The animated cover is a separate lit-typographic-motion page; these are the stills.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = process.env.BRAND_FONTS;
if (!root) throw new Error("BRAND_FONTS must point at the brand font directory");
const pretendard = readFileSync(join(root, "WGDisplay-860.woff2")).toString("base64");
const meslo = readFileSync(join(root, "MesloLGSNF-Regular.woff2")).toString("base64");

const themes = {
  dark: {
    paper: "#16161e",
    ink: "#c0caf5",
    muted: "#a9b1d6",
    line: "#3b4261",
    blue: "#7aa2f7",
    green: "#9ece6a",
    cyan: "#7dcfff",
    node: "#1a1b26",
    bar: "#c0caf5",
    barInk: "#1a1b26",
  },
  light: {
    paper: "#e1e2e7",
    ink: "#1f2335",
    muted: "#3b4261",
    line: "#8c90a4",
    blue: "#2459c9",
    green: "#3d6b1f",
    cyan: "#0b6e8a",
    node: "#f4f5f8",
    bar: "#1f2335",
    barInk: "#e1e2e7",
  },
};

function html(theme, wide) {
  const t = themes[theme];
  const w = wide ? 1200 : 390;
  const h = wide ? 600 : 640;
  const titleSize = wide ? 64 : 36;
  const pipe = wide
    ? `<svg x="640" y="150" width="500" height="280" viewBox="0 0 500 280">
        <text x="0" y="28" fill="${t.muted}" font-family="Meslo, monospace" font-size="14">SAMPLE FLOWLINE</text>
        <rect x="0" y="70" width="88" height="56" fill="${t.node}" stroke="${t.blue}" stroke-width="2"/>
        <text x="44" y="104" text-anchor="middle" fill="${t.ink}" font-family="Meslo, monospace" font-size="14">SOURCE</text>
        ${[0, 1, 2, 3, 4].map((i) => `<rect x="${108 + i * 52}" y="78" width="44" height="40" fill="${t.node}" stroke="${t.cyan}" stroke-width="2"/><text x="${130 + i * 52}" y="104" text-anchor="middle" fill="${t.ink}" font-family="Meslo, monospace" font-size="14">0${i + 1}</text>`).join("")}
        <rect x="380" y="70" width="88" height="56" fill="${t.node}" stroke="${t.green}" stroke-width="2"/>
        <text x="424" y="104" text-anchor="middle" fill="${t.ink}" font-family="Meslo, monospace" font-size="14">SINK</text>
        <text x="0" y="170" fill="${t.muted}" font-family="Meslo, monospace" font-size="13">sections are a sample drawing</text>
      </svg>`
    : `<svg x="24" y="300" width="342" height="180" viewBox="0 0 342 180">
        <text x="0" y="22" fill="${t.muted}" font-family="Meslo, monospace" font-size="13">SAMPLE FLOWLINE</text>
        <rect x="0" y="40" width="70" height="44" fill="${t.node}" stroke="${t.blue}" stroke-width="2"/>
        <text x="35" y="68" text-anchor="middle" fill="${t.ink}" font-family="Meslo, monospace" font-size="12">SRC</text>
        ${[0, 1, 2, 3, 4].map((i) => `<rect x="${80 + i * 36}" y="44" width="30" height="36" fill="${t.node}" stroke="${t.cyan}" stroke-width="2"/><text x="${95 + i * 36}" y="68" text-anchor="middle" fill="${t.ink}" font-family="Meslo, monospace" font-size="12">${i + 1}</text>`).join("")}
        <rect x="266" y="40" width="70" height="44" fill="${t.node}" stroke="${t.green}" stroke-width="2"/>
        <text x="301" y="68" text-anchor="middle" fill="${t.ink}" font-family="Meslo, monospace" font-size="12">SINK</text>
      </svg>`;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><style>
@font-face{font-family:WGDisplay;src:url("data:font/woff2;base64,${pretendard}") format("woff2");font-weight:860;font-display:block}
@font-face{font-family:Meslo;src:url("data:font/woff2;base64,${meslo}") format("woff2");font-weight:400;font-display:block}
html,body{margin:0;width:${w}px;height:${h}px;overflow:hidden;background:${t.paper}}
svg{display:block}
</style></head><body><svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
<rect width="${w}" height="${h}" fill="${t.paper}"/>
<rect x="0" y="0" width="${w}" height="4" fill="${t.blue}"/>
<text x="32" y="56" fill="${t.muted}" font-family="Meslo, monospace" font-size="14" letter-spacing="1.2">~/olga-companion</text>
<text x="32" y="${wide ? 180 : 130}" fill="${t.ink}" font-family="WGDisplay, sans-serif" font-size="${titleSize}" font-weight="860">OLGA</text>
<text x="32" y="${wide ? 250 : 176}" fill="${t.ink}" font-family="WGDisplay, sans-serif" font-size="${titleSize}" font-weight="860">COMPANION</text>
<text x="32" y="${wide ? 310 : 230}" fill="${t.cyan}" font-family="Meslo, monospace" font-size="${wide ? 18 : 15}">Approve each step.</text>
${pipe}
<rect x="0" y="${h - 36}" width="${w}" height="36" fill="${t.bar}"/>
<text x="32" y="${h - 13}" fill="${t.barInk}" font-family="Meslo, monospace" font-size="13">Windows x64   licensed OLGA   approval required</text>
</svg></body></html>`;
}

mkdirSync(here, { recursive: true });
for (const theme of ["dark", "light"]) {
  writeFileSync(join(here, `poster-${theme}.html`), html(theme, true));
  writeFileSync(join(here, `poster-${theme}-narrow.html`), html(theme, false));
}
console.log("posters written");
