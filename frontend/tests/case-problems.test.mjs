import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  FOCUS_TOPOLOGY_NODE_EVENT,
  focusTopologyNode,
  parseFocusNodeEvent,
  publishCaseProblems,
  resetCaseProblems,
  subscribeCaseProblems,
} from '../src/shell/caseProblems.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('case problems publish to every subscriber and reset cleanly', () => {
  resetCaseProblems();
  const seen = [];
  const stop = subscribeCaseProblems((problems) => seen.push(problems));
  publishCaseProblems([
    { id: 'pvt-1', severity: 'error', title: 'tab unreadable', source: 'pvt', nodeId: null },
    { id: 'val-1', severity: 'warning', title: 'roughness band', source: 'validation', nodeId: 'PIPE-01' },
  ]);
  assert.equal(seen.length, 1);
  assert.equal(seen[0].length, 2);
  assert.equal(seen[0][1].nodeId, 'PIPE-01');
  stop();
  publishCaseProblems([]);
  assert.equal(seen.length, 1, 'unsubscribed listeners stay silent');
  resetCaseProblems();
});

test('problem focus requests carry the node id through a typed event', () => {
  assert.equal(FOCUS_TOPOLOGY_NODE_EVENT, 'olga:focus-topology-node');
  const event = focusTopologyNode('PIPE-01');
  assert.equal(event.type, FOCUS_TOPOLOGY_NODE_EVENT);
  assert.equal(parseFocusNodeEvent(event), 'PIPE-01');
  assert.equal(parseFocusNodeEvent(new CustomEvent('other')), null);
});

test('problems panel lists every issue with a show-all path and dispatches focus', async () => {
  const [panel, workspace] = await Promise.all([
    read('../src/shell/ProblemsPanel.tsx'),
    read('../src/WorkspaceView.tsx'),
  ]);
  assert.match(panel, /subscribeCaseProblems/, 'panel reads the shared problem store');
  assert.match(panel, /show-all|showAll/i, 'long lists collapse behind show-all');
  assert.match(panel, /focusTopologyNode|FOCUS_TOPOLOGY_NODE/, 'rows request node focus');
  assert.match(panel, /<Icon name=\{icon\}/, 'rows carry severity icons');
  assert.doesNotMatch(workspace, /slice\(0, 8\)/, 'the 8-item cap is gone from the case surface');
  assert.match(workspace, /publishCaseProblems/, 'the case surface publishes its issues');
});

test('problems tab carries a ticking count badge', async () => {
  const [panel, tabs, css] = await Promise.all([
    read('../src/shell/BottomPanel.tsx'),
    read('../src/ui/Tabs.tsx'),
    read('../src/styles/primitives.css'),
  ]);
  assert.match(panel, /badge: id === 'problems'.*String\(problems\.length\)/, 'badge counts open problems');
  assert.match(tabs, /ui-tab-badge tick/, 'badge ticks once on change');
  assert.match(css, /\.ui-tab-badge\s*\{/, 'badge has a token style contract');
});
