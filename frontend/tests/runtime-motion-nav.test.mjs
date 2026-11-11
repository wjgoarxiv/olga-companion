import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

async function readCss() {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((match) => read(`../src/${match[1]}`)));
  return [root, ...imported].join('\n');
}

test('contextual loading stays quiet for fast work and exposes truthful local status', async () => {
  const loader = await read('../src/ui/ActivityLoader.tsx');

  assert.match(loader, /export function ActivityLoader/);
  assert.match(loader, /setTimeout\(\(\) => setVisible\(true\), 300\)/);
  assert.match(loader, /if \(!visible\) return null/);
  assert.match(loader, /role="status"/);
  assert.match(loader, /aria-busy="true"/);
  assert.match(loader, /activity-loader-label[^]*?\{loadingLabel\}/);
  assert.match(loader, /activity-loader-detail[^]*?\{detail\}/);
  assert.doesNotMatch(loader, /LIVE ACTIVITY|<svg|activity-loader-(?:rail|sweep|halo|node)/);
  assert.doesNotMatch(loader, /\bpercent(?:age)?\b|%|role="progressbar"|aria-valuenow/i, 'indeterminate activity must not fabricate completion');
  assert.doesNotMatch(loader, /stage|step\s+[1-9]|geometry.*solve.*results/is, 'the loader must not invent ordered stages');
});

test('contextual loading uses one restrained motion cue with a static reduced-motion equivalent', async () => {
  const css = await readCss();

  assert.match(css, /\.activity-loader\s*\{[^}]*width:\s*fit-content/s);
  assert.match(css, /\.activity-loader-beacon\s*\{[^}]*background:\s*currentColor/s, 'the beacon is a still square');
  assert.doesNotMatch(css, /\.activity-loader-beacon\s*\{[^}]*animation/s, 'the beacon no longer breathes');
  assert.doesNotMatch(css, /activity-loader-breathe/, 'no breathing keyframes');
  assert.doesNotMatch(css, /activity-loader-(?:traverse|station-pulse|sweep|halo)/);
  assert.match(css, /html\[data-motion="full"\] \.activity-loader-pixels\s*\{[^}]*animation:\s*pixel-loader[^;]*steps\(3, end\)/s, 'the one looping mark is the stepped pixel loader, Full only (the label still carries Off and Subtle)');
});

test('known operational waits use ActivityLoader while content-shape placeholders remain available', async () => {
  const run = await read('../src/RunViewOverview.tsx');
  const workspace = await read('../src/WorkspaceView.tsx');
  const skeleton = await read('../src/ui/Skeleton.tsx');
  const flowpath = await read('../src/FlowpathDetailPanel.tsx');

  assert.match(run, /import \{ ActivityLoader \} from '\.\/ui\/ActivityLoader'/);
  assert.match(run, /<ActivityLoader[^>]*loadingLabel=\{t\('run\.readingCase'\)\}/s);
  const restoring = run.slice(run.indexOf('{!activeLoaded && ('), run.indexOf('{activeLoaded && !contextUnavailable'));
  assert.doesNotMatch(restoring, /aria-live=/, 'the ActivityLoader is the only live status in the restoring branch');
  assert.equal((restoring.match(/t\('run\.readingCase'\)/g) ?? []).length, 1, 'the restoring label is announced and rendered once');
  assert.match(workspace, /import \{ ActivityLoader \} from '\.\/ui\/ActivityLoader'/);
  assert.match(workspace, /<ActivityLoader[^>]*loadingLabel="Parsing network…"/s);
  assert.match(skeleton, /import \{ ActivityLoader \} from '\.\/ActivityLoader'/);
  assert.match(skeleton, /visuallyHidden = false/, 'inventory waits expose their loading label by default');
  assert.match(skeleton, /<ActivityLoader[^>]*loadingLabel=\{loadingLabel\}/s, 'shape placeholders reuse the visible shared activity console');
  assert.match(flowpath, /import \{ ActivityLoader \} from '\.\/ui\/ActivityLoader'/);
  assert.match(flowpath, /<ActivityLoader[^>]*loadingLabel="Reading endpoint and section geometry…"/s);
});

test('status bar carries one runtime item, model and locale in a thin single-state strip', async () => {
  const [app, status, css] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/StatusBar.tsx'),
    readCss(),
  ]);

  assert.match(app, /<StatusBar[\s\S]*?state=\{runtime\.state\}/, 'runtime recovery is visible in the top-level navigation');
  assert.match(status, /wb-status-runtime/, 'one runtime item opens the runtime popover');
  assert.match(status, /className="wb-status-model-name"/, 'the model identity keeps its own readout');
  assert.match(status, /className="wb-status-locale"/, 'the locale keeps its own readout');
  assert.match(status, /stateKey\(state\)/, 'a single presenter maps every runtime state');
  assert.doesNotMatch(status, /<RuntimeNavStatus|<EnvDrawer|sidebar-credit/, 'the strip owns the only runtime surface');
  assert.match(css, /\.wb-status\s*\{[^}]*height:\s*var\(--sb-h\)/s, 'the bar stays inside the 24-28px frame token');
  assert.doesNotMatch(css, /wb-beat|\.wb-heartbeat[^}]*animation/s, 'the sidecar heartbeat is a still square (no blinking)');
  assert.doesNotMatch(css, /hd-ksoe-black-eng\.png|corporate-ci/, 'HD KSOE CI no longer crowds the header');
});
