import { layoutDiagram, type DiagramModel } from './exampleDiagramLayout.mjs';

const short = (id: string) => (id.length > 11 ? `${id.slice(0, 10)}…` : id);

/** A small flow drawing of what an example builds, drawn from the example's own case. */
export function ExampleDiagram({ model, label }: { readonly model: DiagramModel; readonly label: string }) {
  const view = layoutDiagram(model);
  const ground = view.ground;
  return (
    <svg className="example-dia" viewBox={`0 0 ${view.width} ${view.height}`} role="img" aria-label={label}>
      {ground !== null && (
        <g className="example-dia-ground">
          <line x1={8} x2={view.width - 8} y1={ground} y2={ground} />
          {Array.from({ length: Math.floor((view.width - 16) / 12) }, (_, i) => (
            <line key={i} x1={14 + i * 12} y1={ground} x2={8 + i * 12} y2={ground + 6} />
          ))}
        </g>
      )}
      {view.paths.map((path) => (
        <g key={path.id} className="example-dia-pipe">
          <polyline points={path.points.map(([x, y]) => `${x},${y}`).join(' ')} />
          {path.valves.map((valve, i) => (
            <path
              key={i}
              className={valve.scheduled ? 'example-dia-valve is-scheduled' : 'example-dia-valve'}
              d={`M${valve.x - 6},${valve.y - 5} L${valve.x + 6},${valve.y + 5} L${valve.x + 6},${valve.y - 5} L${valve.x - 6},${valve.y + 5} Z`}
            />
          ))}
        </g>
      ))}
      {view.nodes.map((node) => (
        <g key={node.id} className={`example-dia-node is-${node.kind}`}>
          {node.kind === 'sink' && <rect x={node.x - 6} y={node.y - 10} width={12} height={20} />}
          {node.kind === 'source' && <rect x={node.x - 5} y={node.y - 5} width={10} height={10} />}
          {node.kind === 'closed' && <rect x={node.x - 5} y={node.y - 5} width={10} height={10} />}
          {node.kind === 'junction' && <path d={`M${node.x},${node.y - 6} L${node.x + 6},${node.y} L${node.x},${node.y + 6} L${node.x - 6},${node.y} Z`} />}
          <text x={node.x} y={node.labelBelow ? node.y + (node.kind === 'sink' ? 24 : 19) : node.y - (node.kind === 'sink' ? 15 : 10)} textAnchor={node.x < 40 ? 'start' : node.x > view.width - 40 ? 'end' : 'middle'}>{short(node.id)}</text>
        </g>
      ))}
    </svg>
  );
}
