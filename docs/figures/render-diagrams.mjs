// Builds the two README diagrams (architecture, flowchart) in dark and light.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const fontFile = process.env.PRETENDARD_WOFF2;
if (!fontFile) throw new Error("PRETENDARD_WOFF2 must point at Pretendard-latin.woff2");
const font = readFileSync(fontFile).toString("base64");

const themes = {
  dark: {
    paper: "#16161e",
    ink: "#c0caf5",
    muted: "#a9b1d6",
    node: "#1f2335",
    line: "#3b4261",
    blue: "#7aa2f7",
    green: "#9ece6a",
    cyan: "#7dcfff",
    page: "#16161e",
  },
  light: {
    paper: "#e1e2e7",
    ink: "#1f2335",
    muted: "#3b4261",
    node: "#f7f8fa",
    line: "#8c90a4",
    blue: "#2459c9",
    green: "#3d6b1f",
    cyan: "#0b6e8a",
    page: "#e1e2e7",
  },
};

function esc(s) {
  return s.replaceAll("&", "&amp;").replaceAll("<", "&lt;");
}

function page({ id, type, variant, title, desc, body, theme }) {
  const t = themes[theme];
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title><style>@font-face{font-family:Pretendard;src:url("data:font/woff2;base64,${font}") format("woff2");font-weight:100 900;font-display:swap}*{box-sizing:border-box}body{margin:0;padding:16px;background:${t.page};font-family:Pretendard,system-ui,sans-serif}main{width:min(100%,1080px);margin:0 auto}svg{display:block;width:100%;height:auto;font-family:Pretendard,system-ui,sans-serif}text{font-family:Pretendard,system-ui,sans-serif}</style></head><body><main data-type="${type}" data-variant="${variant}"><svg xmlns="http://www.w3.org/2000/svg" id="${id}" viewBox="0 0 1080 640" font-family="Pretendard, sans-serif" role="img" aria-labelledby="${id}-title ${id}-desc"><title id="${id}-title">${esc(title)}</title><desc id="${id}-desc">${esc(desc)}</desc><defs><marker id="arrow-${id}" markerWidth="14" markerHeight="12" refX="13" refY="6" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0 L0 12 L13 6 z" fill="${t.muted}"/></marker></defs><rect width="1080" height="640" fill="${t.paper}"/>${body(t, id)}</svg></main></body></html>`;
}

function node(t, { id, x, y, w, h, stroke, sw = 1.6 }) {
  const cx = x + w / 2;
  const cy = y + h / 2 + 6;
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="0" fill="${t.node}" stroke="${stroke}" stroke-width="${sw}" data-node-id="${esc(id)}"/><text x="${cx}" y="${cy}" text-anchor="middle" font-size="16" font-weight="600" fill="${t.ink}" data-role="node" data-node-for="${esc(id)}">${esc(id)}</text>`;
}

function edge(t, id, d, from, to, label, lx, ly) {
  return `<path d="${d}" fill="none" stroke="${t.muted}" stroke-width="2.2" marker-end="url(#arrow-${id})" data-from="${esc(from)}" data-to="${esc(to)}" data-label="${esc(label)}"/><text x="${lx}" y="${ly}" text-anchor="middle" font-size="13" font-weight="500" fill="${t.muted}" data-role="edge" data-edge-for="${esc(from)}|${esc(to)}">${esc(label)}</text>`;
}

function architecture(t, id) {
  const W = 168;
  const H = 56;
  const parts = [];
  parts.push(`<text x="48" y="52" text-anchor="start" font-size="28" font-weight="650" fill="${t.ink}" data-role="title">Where a case runs</text>`);
  parts.push(`<text x="48" y="88" text-anchor="start" font-size="15" font-weight="400" fill="${t.muted}">The shell talks to a local sidecar. The provider, OLGA and the workspace sit outside.</text>`);
  parts.push(`<rect x="36" y="128" width="712" height="476" fill="none" stroke="${t.blue}" stroke-width="1.5" stroke-dasharray="8 6" data-trust-boundary="app" data-boundary-name="app" data-group-id="app"/>`);
  parts.push(`<text x="48" y="118" text-anchor="start" font-size="13" font-weight="600" fill="${t.blue}" data-role="boundary" data-boundary-for="app">On this PC</text>`);

  const box = (id, x, y, stroke) => parts.push(node(t, { id, x, y, w: W, h: H, stroke }));
  box("Tauri shell", 56, 168, t.blue);
  box("Python sidecar", 292, 168, t.cyan);
  box("Chat agent", 528, 168, t.cyan);
  box("Case pipeline", 292, 320, t.line);
  box("Run supervisor", 528, 320, t.line);
  box("Result reader", 528, 472, t.green);
  box("AI provider", 860, 168, t.green);
  box("OLGA", 860, 320, t.green);
  box("Workspace", 860, 472, t.green);

  const mid = (y) => y + H / 2;
  parts.push(edge(t, id, `M${56 + W} ${mid(168)} H292`, "Tauri shell", "Python sidecar", "loopback", 258, 184));
  parts.push(edge(t, id, `M${292 + W} ${mid(168)} H528`, "Python sidecar", "Chat agent", "hosts", 494, 184));
  parts.push(edge(t, id, `M${528 + W} ${mid(168)} H860`, "Chat agent", "AI provider", "API", 778, 184));
  parts.push(edge(t, id, `M560 ${168 + H} V280 H376 V320`, "Chat agent", "Case pipeline", "cases", 468, 268));
  parts.push(edge(t, id, `M612 ${168 + H} V320`, "Chat agent", "Run supervisor", "runs", 636, 268));
  parts.push(edge(t, id, `M${528 + W} ${mid(320)} H860`, "Run supervisor", "OLGA", "opi.exe", 778, 336));
  parts.push(edge(t, id, `M612 ${320 + H} V472`, "Run supervisor", "Result reader", "outputs", 636, 420));
  parts.push(edge(t, id, `M376 ${320 + H} V568 H944 V528`, "Case pipeline", "Workspace", "save", 640, 556));

  parts.push(`<text x="48" y="632" font-size="13" fill="${t.muted}">Blue shell. Cyan sidecar. Green is outside the app, or a result.</text>`);
  return parts.join("");
}

function workflow(t, id) {
  const W = 200;
  const H = 64;
  const parts = [];
  parts.push(`<text x="48" y="52" text-anchor="start" font-size="28" font-weight="650" fill="${t.ink}" data-role="title">Ask, approve, run, read</text>`);
  parts.push(`<text x="48" y="88" text-anchor="start" font-size="15" font-weight="400" fill="${t.muted}">A write or a run waits on an approval card. A refusal returns to the question.</text>`);

  const box = (nid, x, y, stroke, extra = "") => {
    parts.push(`<rect x="${x}" y="${y}" width="${W}" height="${H}" rx="0" fill="${t.node}" stroke="${stroke}" stroke-width="1.6" data-node-id="${esc(nid)}"${extra}/><text x="${x + W / 2}" y="${y + H / 2 + 6}" text-anchor="middle" font-size="16" font-weight="600" fill="${t.ink}" data-role="node" data-node-for="${esc(nid)}">${esc(nid)}</text>`);
  };
  box("Ask", 64, 168, t.blue);
  box("Propose", 420, 168, t.line);
  box("Approve?", 776, 168, t.cyan, ` data-node-type="decision" data-outcomes="Yes|No"`);
  box("Run OLGA", 776, 340, t.green);
  box("Read results", 776, 500, t.green);

  const my = (y) => y + H / 2;
  parts.push(edge(t, id, `M${64 + W} ${my(168)} H420`, "Ask", "Propose", "describe", 342, 156));
  parts.push(edge(t, id, `M${420 + W} ${my(168)} H776`, "Propose", "Approve?", "card", 698, 156));
  parts.push(edge(t, id, `M${776 + W / 2} ${168 + H} V340`, "Approve?", "Run OLGA", "Yes", 910, 300));
  parts.push(edge(t, id, `M${776 + W / 2} ${340 + H} V500`, "Run OLGA", "Read results", "files", 910, 470));
  parts.push(edge(t, id, `M800 ${168 + H} V300 H164 V${168 + H}`, "Approve?", "Ask", "No", 480, 288));
  parts.push(`<text x="48" y="620" font-size="13" fill="${t.muted}">Yes continues. No returns to the question. Nothing runs before the card.</text>`);
  return parts.join("");
}

const archDesc = "The shell talks to a local sidecar. The AI provider, OLGA and the workspace sit outside that process.";
const flowDesc = "A write or a run waits on an approval card. A refusal returns to the question.";

for (const theme of ["dark", "light"]) {
  writeFileSync(join(here, `architecture-${theme}.html`), page({
    id: `architecture-${theme}`,
    type: "architecture",
    variant: theme,
    title: "Where a case runs",
    desc: archDesc,
    body: architecture,
    theme,
  }));
  writeFileSync(join(here, `workflow-${theme}.html`), page({
    id: `workflow-${theme}`,
    type: "flowchart",
    variant: theme,
    title: "Ask, approve, run, read",
    desc: flowDesc,
    body: workflow,
    theme,
  }));
}
console.log("wrote four diagrams");
