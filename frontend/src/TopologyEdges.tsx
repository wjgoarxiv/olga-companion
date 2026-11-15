import { resolveLabelCollisions, routeParallelEdge } from './topologyEdgeRoutes';

type Edge = {
  readonly source: string;
  readonly target: string;
  readonly label: string;
};

type Position = {
  readonly x: number;
  readonly y: number;
};

type TopologyEdgeLayerProps = {
  readonly edges: readonly Edge[];
  readonly positions: Readonly<Record<string, Position>>;
  readonly offsets: readonly number[];
  readonly nodeWidth: number;
  readonly nodeHeight: number;
  readonly onSelect: (index: number, label: string) => void;
};

type TopologyEdgeLabelsProps = TopologyEdgeLayerProps & {
  /** Rendered label size in SVG units; hit boxes and collision widths follow it. */
  readonly labelFontSize?: number;
};

type TopologyEdgePathsProps = TopologyEdgeLayerProps & {
  readonly selectedIndex: number | null;
};

function routedEdges({
  edges, positions, offsets, nodeWidth, nodeHeight,
}: Omit<TopologyEdgeLayerProps, 'onSelect'>) {
  return edges.flatMap((edge, index) => {
    const source = positions[edge.source];
    const target = positions[edge.target];
    if (!source || !target) return [];
    const route = routeParallelEdge({
      x1: source.x + nodeWidth,
      y1: source.y + nodeHeight / 2,
      x2: target.x,
      y2: target.y + nodeHeight / 2,
      offset: offsets[index] ?? 0,
    });
    return [{ edge, index, route }];
  });
}

export function TopologyEdgePaths({
  edges, positions, offsets, selectedIndex, nodeWidth, nodeHeight, onSelect,
}: TopologyEdgePathsProps) {
  const routed = routedEdges({ edges, positions, offsets, nodeWidth, nodeHeight });

  return (
    <>
      {routed.map(({ edge, index, route }) => (
        <g
          key={`edge-${index}`}
          data-flowpath-index={index}
          data-flowpath-offset={route.offset}
          className={`topo-edge ${selectedIndex === index ? 'selected' : ''}`}
          tabIndex={0}
          role="button"
          aria-label={`Inspect flowpath ${edge.label} from ${edge.source} to ${edge.target}`}
          aria-pressed={selectedIndex === index}
          onMouseDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onSelect(index, edge.label);
          }}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            onSelect(index, edge.label);
          }}
        >
          <path className="topo-edge-hit" d={route.path} />
          <path className="topo-edge-line" d={route.path} markerEnd="url(#topo-arrow)" />
        </g>
      ))}
    </>
  );
}

const MONO_ADVANCE = 0.62;

export function TopologyEdgeLabels({
  edges, positions, offsets, nodeWidth, nodeHeight, onSelect, labelFontSize = 11,
}: TopologyEdgeLabelsProps) {
  const routed = routedEdges({ edges, positions, offsets, nodeWidth, nodeHeight });
  const labels = resolveLabelCollisions(routed.map(({ edge, route }) => ({
    x: route.labelX,
    y: route.labelY,
    width: Math.max(28, edge.label.length * labelFontSize * MONO_ADVANCE + 8),
  })));

  return (
    <>
      <g className="topo-edge-label-layer">
        {routed.map(({ edge, index }, labelIndex) => {
          const label = labels[labelIndex];
          if (!label) return null;
          return (
            <g
              key={`edge-label-${index}`}
              data-flowpath-label-index={index}
              className="topo-edge-label-target"
              aria-hidden="true"
              onMouseDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                onSelect(index, edge.label);
              }}
            >
              {/* Transparent hit box capped at the 20-unit collision lane: taller would steal clicks from neighboring labels. */}
              <rect x={label.x - label.width / 2} y={label.y - 14} width={label.width} height={20} rx={0} />
              <text x={label.x} y={label.y} className="topo-edge-label" textAnchor="middle">{edge.label}</text>
            </g>
          );
        })}
      </g>
    </>
  );
}
