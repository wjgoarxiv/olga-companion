import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const routingModule = new URL('../src/topologyEdgeRoutes.ts', import.meta.url);
const [edgeLayer, topologyMap] = await Promise.all([
  readFile(new URL('../src/TopologyEdges.tsx', import.meta.url), 'utf8').catch(() => ''),
  readFile(new URL('../src/TopologyMap.tsx', import.meta.url), 'utf8'),
]);

test('parallel flowpaths receive symmetric distinct offsets when endpoints match', async () => {
  // Given
  const { parallelEdgeOffsets } = await import(routingModule.href);
  const edges = [
    { source: 'NODE_A', target: 'NODE_B' },
    { source: 'NODE_A', target: 'NODE_B' },
    { source: 'NODE_A', target: 'NODE_B' },
  ];

  // When
  const offsets = parallelEdgeOffsets(edges);

  // Then
  assert.deepEqual(offsets, [-24, 0, 24]);
});

test('parallel flowpath routes separate both hit targets and labels', async () => {
  // Given
  const { parallelEdgeOffsets, routeParallelEdge } = await import(routingModule.href);
  const offsets = parallelEdgeOffsets([
    { source: 'NODE_A', target: 'NODE_B' },
    { source: 'NODE_A', target: 'NODE_B' },
  ]);

  // When
  const routes = offsets.map((offset) => routeParallelEdge({
    x1: 150,
    y1: 80,
    x2: 300,
    y2: 80,
    offset,
  }));

  // Then
  assert.equal(new Set(routes.map((route) => `${route.path}|${route.labelY}`)).size, 2);
});

test('overlapping flowpath labels receive non-overlapping positions', async () => {
  // Given
  const { resolveLabelCollisions } = await import(routingModule.href);
  const labels = [
    { x: 200, y: 100, width: 80 },
    { x: 200, y: 100, width: 80 },
    { x: 200, y: 100, width: 80 },
  ];

  // When
  const placed = resolveLabelCollisions(labels);

  // Then
  assert.equal(new Set(placed.map((label) => `${label.x}|${label.y}`)).size, labels.length);
  assert.ok(placed.every((label, index) => placed.slice(index + 1).every(
    (other) => Math.abs(label.x - other.x) >= 84 || Math.abs(label.y - other.y) >= 20,
  )));
});

test('flowpath labels provide a pointer target above crossing edge strokes', () => {
  // Given
  const expectedPointerLayer = /data-flowpath-label-index[\s\S]*topo-edge-label-target/;

  // When
  const renderedEdges = edgeLayer;

  // Then
  assert.match(renderedEdges, expectedPointerLayer);
});

test('flowpath label targets render after nodes so nodes cannot intercept them', () => {
  // Given
  const expectedLayerOrder = /<TopologyEdgePaths[\s\S]*laid\.placed\.map[\s\S]*<TopologyEdgeLabels/;

  // When
  const renderedTopology = topologyMap;

  // Then
  assert.match(renderedTopology, expectedLayerOrder);
});
