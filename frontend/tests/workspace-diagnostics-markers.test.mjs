import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readSessionSource } from './session-source.mjs';

const read = (p) => readFile(new URL(p, import.meta.url), 'utf8');
const readCss = async () => {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((m) => read('../src/' + m[1])));
  return [root, ...imported].join('\n');
};

test('capability matrix is demoted to a quiet environment drawer, not a front headline', async () => {
  const app = await read('../src/App.tsx');
  assert.match(app, /<StatusBar/);
  assert.doesNotMatch(app, /<EnvDrawer|<RuntimeNavStatus/, 'no duplicate runtime pills beside the status item');
  const [drawer, ko] = await Promise.all([
    read('../src/EnvDrawer.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(drawer, /t\('env\.gated'\)/);
  assert.match(drawer, /t\('env\.available'\)/);
  assert.match(ko, /'env\.gated': '제한됨'/);
  assert.match(ko, /'env\.available': '사용 가능'/);
  assert.match(drawer, /publication_export:\s*'Publication Export'/, 'publication renderer readiness has an operator-facing label');
  assert.doesNotMatch(drawer, /cap\.enabled \? 'Ready'/, 'executable availability must not claim runtime health');
  // Gated is a neutral designed state: styled by the .capability.gated rule in
  // the mute colour, never a warning/amber tone.
  const css = await readCss();
  assert.match(css, /\.capability\.gated strong\s*\{\s*color:\s*var\(--mute\)/);
  assert.match(css, /\.conn\s*\{[^}]*min-height:\s*36px/s, 'named diagnostics trigger has a touch-safe hit area');
  assert.match(drawer, /className="conn-label">\{t\('env\.systemStatus'\)\}</, 'the trigger purpose is visible instead of dot-only');
  assert.match(css, /\.conn::after\s*\{[^}]*width:\s*7px[^}]*height:\s*7px/s, 'the secondary connection signal stays visually compact');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.env-popover\s*\{[\s\S]*?position:\s*fixed[\s\S]*?left:\s*10px[\s\S]*?right:\s*10px/s, 'mobile diagnostics popover is viewport-bound');
  assert.doesNotMatch(css, /\.env-popover\s*\{\s*right:\s*auto;\s*left:\s*0;?\s*\}/, 'no stale mobile override can unbind diagnostics');
  assert.doesNotMatch(css, /#f5a623|#ffa500|#ffbf00|amber/i);
});

test('vite config uses OLGA ports and sidecar proxy', async () => {
  const config = await read('../vite.config.ts');
  assert.match(config, /5273/);
  assert.match(config, /8865/);
  assert.doesNotMatch(config, /5173/);
  assert.doesNotMatch(config, /8765/);
});

test('production chrome has a local favicon and accessible workflow nav', async () => {
  const html = await read('../index.html');
  assert.match(html, /rel="icon"/);
  assert.match(html, /favicon.svg/);
  const pkg = await read('../../package.json');
  assert.match(pkg, /"lucide-react"/);
  const sidebar = await read('../src/Sidebar.tsx');
  assert.match(sidebar, /from 'lucide-react'/);
  assert.match(sidebar, /aria-label=\{it\.label\}/);
  assert.match(sidebar, /title=\{it\.label\}/);
  assert.match(sidebar, /<Icon className="nav-icon"/);
  assert.doesNotMatch(sidebar, /\{it\.icon\}/);
});

test('tauri config is branded and port-safe', async () => {
  const config = await read('../../src-tauri/tauri.conf.json');
  assert.match(config, /5273/);
  assert.match(config, /8865/);
  assert.doesNotMatch(config, /HYSYS Companion/);
});

test('workspace bar: active-case chip + file list, path-free case selection', async () => {
  const [app, bar] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/TitleBar.tsx'),
  ]);
  assert.match(bar, /<WorkspaceBar/, 'the title-bar breadcrumb owns case context without a twin');
  assert.match(app, /activeCaseName/);
  const s = await readSessionSource(import.meta.url);
  assert.match(s, /fetchWorkspace/);
  assert.match(s, /setActiveCase/);
  const wb = await read('../src/WorkspaceBar.tsx');
  assert.match(wb, /case-chip/, 'an active-case chip');
  assert.match(wb, /onPick/, 'cases are picked from the list…');
  assert.match(wb, /c\.rel/, '…by their workspace-relative id, not a typed path');
});

test('chat history is labelled "Chats" with a per-item delete', async () => {
  const [sm, en] = await Promise.all([
    read('../src/SessionMenu.tsx'),
    read('../src/i18n/en.ts'),
  ]);
  assert.match(sm, /\{t\('chat\.chats'\)\}/, 'the menu is labelled Chats, not the ambiguous Sessions');
  assert.match(en, /'chat\.chats': 'Chats'/, 'en history trigger is exact');
  assert.match(sm, /onDelete/);
  assert.match(sm, /session-delete/, 'a per-item delete control');
  const controller = await read('../src/useChatController.ts');
  assert.match(controller, /deleteChat/);
  const s = await readSessionSource(import.meta.url);
  assert.match(s, /deleteSession/);
});

test('interactive topology map (dagre layout + self-contained SVG) renders network graphs', async () => {
  const tm = await read('../src/TopologyMap.tsx');
  assert.match(tm, /@dagrejs\/dagre/, 'dagre computes the layout');
  assert.match(tm, /rankdir:\s*'LR'/, 'left-to-right PFD layout');
  assert.match(tm, /<svg/, 'self-contained SVG renderer (React Flow edges never measured in the timeline)');
  assert.match(tm, /onWheel/, 'scroll to zoom');
  assert.match(tm, /setSelected/, 'click a node for detail');
  assert.doesNotMatch(tm, /@xyflow/, 'no React Flow dependency');
  const eb = await read('../src/EvidenceBlock.tsx');
  assert.match(eb, /isNetwork/, 'a network result routes to the map');
  assert.match(eb, /TopologyMap/);
  const pkg = JSON.parse(await read('../../package.json'));
  assert.ok(pkg.dependencies['@dagrejs/dagre'], 'dagre is a bundled dep (CSP)');
});

test('reasoning-effort picker (codex-only) → x-llm-variant header', async () => {
  const pp = await read('../src/ProviderPanel.tsx');
  assert.match(pp, /supportsEffort/, 'effort control is gated');
  assert.match(pp, /provider === 'openai'/, '…to codex/openai only');
  assert.match(pp, /onEffort/);
  assert.match(pp, /xhigh|EFFORT_OPTIONS/, 'the four effort tiers');
  const s = await readSessionSource(import.meta.url);
  assert.match(s, /x-llm-variant/, 'the variant rides the request header');
  const app = await read('../src/App.tsx');
  const selection = await read('../src/useProviderSelection.ts');
  assert.match(app, /effort/, 'App holds effort state');
  assert.match(selection, /saveProviderSelection/, 'provider, model, and variant persist in the sidecar');
});

test('the cryptic "N/M ready" capability chip is retired; diagnostics on demand', async () => {
  const drawer = await read('../src/EnvDrawer.tsx');
  // The old top-bar count is gone; capabilities live behind the connection dot.
  assert.doesNotMatch(drawer, /\}\/\{caps\.length\} ready/, 'no cryptic N/M ready count in the chrome');
  assert.match(drawer, /Diagnostics/, 'capabilities relocated to an on-demand Diagnostics popover');
  assert.match(drawer, /className=\{`conn /, 'the connection dot is the diagnostics trigger');
  // Marker #2 still holds: EnvDrawer is mounted and Gated stays neutral (mute, no amber).
  assert.match(drawer, /Gated/);
});
