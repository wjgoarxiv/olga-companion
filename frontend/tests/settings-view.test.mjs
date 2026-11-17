import { readFile, readdir } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readResultsSource } from './results-source.mjs';

const read = (p) => readFile(new URL(p, import.meta.url), 'utf8');
const sourceRoot = new URL('../src/', import.meta.url);
const sourceSuffixes = ['.css', '.js', '.mjs', '.ts', '.tsx'];

async function readSourceFiles(dir = sourceRoot) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.isDirectory()) {
      files.push(...await readSourceFiles(new URL(entry.name + '/', dir)));
    } else if (sourceSuffixes.some((suffix) => entry.name.endsWith(suffix))) {
      const url = new URL(entry.name, dir);
      files.push({ path: url.pathname, text: await readFile(url, 'utf8') });
    }
  }
  return files;
}

async function readCss() {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((m) => read('../src/' + m[1])));
  return [root, ...imported].join('\n');
}

test('settings view: provider/model/effort + native workspace actions (config has a home)', async () => {
  const sv = await read('../src/SettingsView.tsx');
  const results = await readResultsSource(import.meta.url);
  const bar = await read('../src/WorkspaceBar.tsx');
  assert.match(sv, /ProviderPanel/, 'AI provider/model/effort config');
  assert.match(sv, /NativeContextActions/, 'workspace selection uses the native dialog surface');
  assert.match(sv, /workspaceRootLabel/, 'long workspace paths are presented as compact labels');
  assert.doesNotMatch(sv, /<input\b|Workspace path…|onChangeRoot/, 'Settings never accepts a typed workspace path');
  assert.match(sv, /settings-layout/, 'settings uses a sectioned layout, not a narrow form');
  assert.match(sv, /settings-sections/, 'settings has a left section list');
  assert.match(sv, /settings-card provider-card/, 'provider controls live in a clear configuration card');
  assert.match(sv, /settings-card workspace-card/, 'workspace controls live in a clear configuration card');
  assert.doesNotMatch(sv, /settings-context/, 'the header already shows the model and workspace, so Settings does not repeat them');
  assert.doesNotMatch(sv, /`\.genkey`/, 'file extensions are real <code> elements, not literal backticks');
  assert.match(sv, /<code>\.genkey<\/code>/);
  assert.match(sv, /settings-current-row/, 'workspace state is presented as a labeled row');
  assert.doesNotMatch(sv, /\(default\)/, 'Settings must not expose raw internal default labels');
  assert.doesNotMatch(results, /\(default\)/, 'Results must not expose raw internal default labels');
  assert.doesNotMatch(bar, /Folder: \{shortRoot\}/, 'workspace picker must not render an empty folder label');
  assert.match(sv, /workspaceRootLabel/, 'Settings uses the shared operator-facing workspace label');
  assert.match(results, /workspaceRootLabel/, 'Results uses the shared operator-facing workspace label');
  assert.match(bar, /workspaceRootLabel/, 'Workspace picker uses the shared operator-facing workspace label');
  const css = await readCss();
  assert.match(css, /\.case-item-name\s*\{[^}]*min-width:\s*0[^}]*text-overflow:\s*ellipsis/s, 'workspace picker filenames shrink before ellipsis instead of forcing overflow');
  assert.match(css, /\.settings-view\s*\{[^}]*max-width:\s*1040px/s, 'desktop settings uses the workbench width');
  assert.match(css, /\.settings-layout\s*\{[^}]*grid-template-columns:\s*220px minmax\(0,\s*1fr\)/s, 'desktop settings pairs the section list with its panel');
  assert.match(css, /\.settings-card\s*\{[^}]*border:\s*1px solid var\(--hairline-soft\)/s, 'settings cards use the existing hairline system');
  assert.match(css, /\.provider-card \.provider-control\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s, 'desktop settings keeps provider controls inside the provider card');
  assert.match(css, /\.provider-card \.ui-select\s*\{[^}]*width:\s*100%[^}]*max-width:\s*100%[^}]*min-width:\s*0/s, 'settings provider selects stay bounded inside the provider card');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.settings-view\s*\{[\s\S]*?overflow-x:\s*hidden/s, 'mobile settings has no horizontal scroll');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.settings-view\s*\{[\s\S]*?padding:\s*20px 18px 84px/s, 'mobile settings keeps workspace controls clear of bottom nav');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.settings-view\s*\{[\s\S]*?scroll-padding-bottom:\s*84px/s, 'mobile settings scrolls focused controls above bottom nav');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.settings-layout\s*\{[\s\S]*?grid-template-columns:\s*1fr/s, 'mobile settings stacks list above panel');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.provider-control\s*\{[\s\S]*?grid-template-columns:\s*1fr/s, 'mobile provider controls stack');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.native-context-actions\s*\{[\s\S]*?grid-template-columns:\s*1fr/s, 'mobile native workspace actions stay bounded');
  assert.match(css, /\.settings-current\s*\{[^}]*white-space:\s*nowrap[^}]*overflow:\s*hidden[^}]*text-overflow:\s*ellipsis/s, 'current workspace path stays to one scannable line');
  assert.doesNotMatch(css, /\.settings-current\s*\{[^}]*word-break:\s*break-all/s, 'workspace path must not shred into hard-wrapped columns');
  const providerPanel = await read('../src/ProviderPanel.tsx');
  assert.doesNotMatch(providerPanel, /active!/, 'provider panel does not use non-null assertions for model lists');
  assert.match(providerPanel, /operatorModelLabel/, 'provider model options pass through the operator label normalizer');
  assert.match(providerPanel, /operatorEffortLabel/, 'reasoning effort options use English operator labels');
  assert.doesNotMatch(providerPanel, /가장 깊게|깊게|균형|빠르게|최상/, 'provider panel must not mix Korean labels into the English operator UI');
  assert.doesNotMatch(providerPanel, /\{m\.label \?\? m\.id\}/, 'provider panel must not render raw upstream model labels');
  assert.match(providerPanel, /xhigh:\s*'xhigh'/, 'xhigh effort keeps the real API nomenclature');
  assert.match(providerPanel, /medium:\s*'medium'/, 'medium effort keeps the real API nomenclature');
  assert.doesNotMatch(providerPanel, /balanced/, 'legacy balanced copy must not replace the real medium tier');
  assert.doesNotMatch(providerPanel, /label:\s*`\$\{value\}\s*·/, 'effort options do not duplicate raw and marketing labels');
  const sourceFiles = await readSourceFiles();
  const provenanceHits = sourceFiles.flatMap((file) =>
    /HysysCompanion|ported from|v2 mandate|migration|provenance/i.test(file.text) ? [file.path] : []
  );
  assert.deepEqual(provenanceHits, [], 'product source files do not retain migration provenance comments');
  const [app, centre] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/CentreViews.tsx'),
  ]);
  assert.match(centre, /<SettingsView[\s/>]/, 'settings is a real mounted view');
  assert.match(app, /operatorModelLabel/, 'status bar uses normalized operator model labels');
  assert.match(app, /operatorEffortLabel/, 'status bar uses operator-facing effort labels');
  assert.doesNotMatch(app, /\$\{model \|\| 'codex'\} · \$\{effort\}/, 'status bar must not expose raw model/effort copy');
});
