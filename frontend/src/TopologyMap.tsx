import { useMemo, useState, useRef, useLayoutEffect, useEffect, useCallback, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react';
import dagre from '@dagrejs/dagre';
import { TopologyEdgeLabels, TopologyEdgePaths } from './TopologyEdges';
import { TopologyInspector } from './TopologyInspector';
import { parallelEdgeOffsets } from './topologyEdgeRoutes';
import { fitContentView } from './topologyFit';
import { useLocale } from './i18n/index.ts';
import { PixelIconInSvg, type PixelIconName } from './ui/PixelIcon';
import { FrameDecor } from './ui/FrameDecor';
import { formatCoord } from './readoutFormat.mjs';
import { FOCUS_TOPOLOGY_NODE_EVENT, parseFocusNodeEvent } from './shell/caseProblems';
import { nodeLabelFontSize, pickCountKey } from './topologyText.ts';
import type { FlowpathDetails } from './workspaceApi';
/** Interactive OLGA network map: dagre lays backend connectivity left to right,
 *  while pan, zoom, node drag, and click-for-detail stay inside one SVG viewBox. */
export interface NetNode { id: string; label: string; kind: string }
export interface NetEdge { source: string; target: string; label: string; kind: string }
type Selection = { kind: 'node'; id: string } | { kind: 'edge'; index: number };
const NODE_W = 150;
const NODE_H = 40;
const PAD = 30;
function isJunction(kind: string) {
  return kind.includes('NODE'); // NODE, JUNCTIONNODE, …
}

/** Pixel symbol for a topology node kind; a plain pipe stands in for the rest. */
function kindIcon(kind: string): PixelIconName {
  const upper = kind.toUpperCase();
  if (upper.includes('SOURCE')) return 'source';
  if (upper.includes('SINK')) return 'sink';
  if (upper.includes('VALVE')) return 'valve';
  if (upper.includes('RISER')) return 'riser';
  if (upper.includes('SEPARATOR')) return 'separator';
  if (isJunction(upper)) return 'node';
  return 'pipe';
}
interface Placed extends NetNode { x: number; y: number }
/** Gap between node columns: at least the old 92, wide enough for the longest flowpath name to sit between its nodes. */
function rankSeparation(netEdges: NetEdge[]) {
  const longest = netEdges.reduce((max, edge) => Math.max(max, edge.label.length), 0);
  return Math.min(220, Math.max(92, longest * 11 + 40));
}
function layout(netNodes: NetNode[], netEdges: NetEdge[]) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: rankSeparation(netEdges), marginx: PAD, marginy: PAD });
  g.setDefaultEdgeLabel(() => ({}));
  const ids = new Set(netNodes.map((n) => n.id));
  netNodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  const kept = netEdges.filter((e) => ids.has(e.source) && ids.has(e.target));
  kept.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  const placed: Placed[] = netNodes.map((n) => {
    const p = g.node(n.id);
    return { ...n, x: (p?.x ?? PAD) - NODE_W / 2, y: (p?.y ?? PAD) - NODE_H / 2 };
  });
  const gr = g.graph();
  return { placed, edges: kept, width: (gr.width as number) || 400, height: (gr.height as number) || 200 };
}
export default function TopologyMap({
  nodes: netNodes,
  edges: netEdges,
  counts,
  truncated,
  flowpathDetails = null,
  flowpathLoading = false,
  flowpathError = '',
  scanning = false,
  onFlowpathSelect,
}: {
  nodes: NetNode[];
  edges: NetEdge[];
  counts?: { nodes: number; flowpaths: number; edges: number };
  truncated?: boolean;
  flowpathDetails?: FlowpathDetails | null;
  flowpathLoading?: boolean;
  flowpathError?: string;
  scanning?: boolean;
  onFlowpathSelect?: (flowpath: string | null) => void;
}) {
  const laid = useMemo(() => layout(netNodes, netEdges), [netNodes, netEdges]);
  const edgeOffsets = useMemo(() => parallelEdgeOffsets(laid.edges), [laid.edges]);
  const topologyKey = `${netNodes.map((node) => node.id).join('|')}::${netEdges.map((edge) => `${edge.source}>${edge.target}:${edge.label}`).join('|')}`;
  const [pos, setPos] = useState<Record<string, { x: number; y: number }>>(() =>
    Object.fromEntries(laid.placed.map((n) => [n.id, { x: n.x, y: n.y }]))
  );
  const [view, setView] = useState(() => fitContentView(laid.placed, { nodeW: NODE_W, nodeH: NODE_H, pad: PAD }));
  const [selected, setSelected] = useState<Selection | null>(null);
  const [canvasW, setCanvasW] = useState(0);
  const [minimapOpen, setMinimapOpen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const { t } = useLocale();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const coordRef = useRef<HTMLSpanElement | null>(null);
  const drag = useRef<{ kind: 'pan' | 'node'; id?: string; sx: number; sy: number; ox: number; oy: number; cx: number; cy: number } | null>(null);
  const moved = useRef(false);
  // Reset when a different case is loaded.
  useLayoutEffect(() => {
    setPos(Object.fromEntries(laid.placed.map((n) => [n.id, { x: n.x, y: n.y }])));
    setView(fitContentView(laid.placed, { nodeW: NODE_W, nodeH: NODE_H, pad: PAD }));
    setSelected(null);
  }, [topologyKey]);
  useLayoutEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const update = () => setCanvasW(el.getBoundingClientRect().width || 0);
    update();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [topologyKey]);
  const labelFs = nodeLabelFontSize(view.w, canvasW || laid.width);
  const toSvg = useCallback((clientX: number, clientY: number) => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r) return { x: 0, y: 0 };
    return { x: view.x + ((clientX - r.left) / r.width) * view.w, y: view.y + ((clientY - r.top) / r.height) * view.h };
  }, [view]);
  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1.12 : 1 / 1.12;
    const p = toSvg(e.clientX, e.clientY);
    setView((v) => {
      const w = Math.max(60, Math.min(v.w * factor, laid.width * 6));
      const h = w * (v.h / v.w);
      return { x: p.x - (p.x - v.x) * (w / v.w), y: p.y - (p.y - v.y) * (h / v.h), w, h };
    });
  }, [toSvg, laid.width]);
  const onDown = (e: React.MouseEvent, id?: string) => {
    moved.current = false;
    const p = toSvg(e.clientX, e.clientY);
    if (id) {
      const cur = pos[id] ?? { x: 0, y: 0 };
      drag.current = { kind: 'node', id, sx: p.x, sy: p.y, ox: cur.x, oy: cur.y, cx: e.clientX, cy: e.clientY };
    } else {
      drag.current = { kind: 'pan', sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y, cx: e.clientX, cy: e.clientY };
    }
  };
  const onMove = (e: React.MouseEvent) => {
    if (!drag.current) return;
    const d = drag.current;
    // Only count as a drag past a small dead-zone, so a click with sub-pixel
    // jitter still selects the node instead of being swallowed.
    if (!moved.current && Math.hypot(e.clientX - d.cx, e.clientY - d.cy) < 3) return;
    moved.current = true;
    const id = d.id;
    if (d.kind === 'node' && id) {
      const p = toSvg(e.clientX, e.clientY);
      setPos((m) => ({ ...m, [id]: { x: d.ox + (p.x - d.sx), y: d.oy + (p.y - d.sy) } }));
    } else {
      const r = svgRef.current?.getBoundingClientRect();
      if (!r) return;
      setView((v) => ({ ...v, x: d.ox - ((e.clientX - d.sx) / r.width) * v.w, y: d.oy - ((e.clientY - d.sy) / r.height) * v.h }));
    }
  };
  const onUp = () => { drag.current = null; };

  const fitView = useCallback(() => {
    setView(fitContentView(laid.placed, { nodeW: NODE_W, nodeH: NODE_H, pad: PAD }));
  }, [laid.placed]);

  const zoomBy = useCallback((factor: number) => {
    setView((v) => {
      const w = Math.max(60, Math.min(v.w * factor, laid.width * 6));
      const h = w * (v.h / v.w);
      const cx = v.x + v.w / 2;
      const cy = v.y + v.h / 2;
      return { x: cx - w / 2, y: cy - h / 2, w, h };
    });
  }, [laid.width]);

  const toggleFullscreen = useCallback(() => {
    const el = wrapRef.current;
    if (!el) return;
    if (document.fullscreenElement) {
      if (typeof document.exitFullscreen === 'function') void document.exitFullscreen().catch(() => undefined);
      return;
    }
    if (typeof el.requestFullscreen === 'function') {
      void el.requestFullscreen().catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    const sync = () => setIsFullscreen(document.fullscreenElement === wrapRef.current);
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);

  useEffect(() => {
    const onFocusRequest = (event: Event) => {
      const nodeId = parseFocusNodeEvent(event);
      if (nodeId === null || !netNodes.some((n) => n.id === nodeId)) return;
      setSelected({ kind: 'node', id: nodeId });
      const safeId = typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
        ? CSS.escape(nodeId)
        : nodeId.replace(/["\\]/g, '');
      requestAnimationFrame(() => {
        svgRef.current?.querySelector<SVGGElement>(`[data-node-id="${safeId}"]`)?.scrollIntoView({ block: 'nearest' });
      });
    };
    window.addEventListener(FOCUS_TOPOLOGY_NODE_EVENT, onFocusRequest);
    return () => window.removeEventListener(FOCUS_TOPOLOGY_NODE_EVENT, onFocusRequest);
  }, [netNodes]);

  if (!netNodes.length) {
    return <p className="chrome-hint">{t('workspace.graphEmpty')}</p>;
  }

  const sel = selected?.kind === 'node' ? netNodes.find((n) => n.id === selected.id) : null;
  const selectedEdge = selected?.kind === 'edge' ? laid.edges[selected.index] : null;
  const inbound = sel ? netEdges.filter((e) => e.target === sel.id).map((e) => e.label).filter(Boolean) : [];
  const outbound = sel ? netEdges.filter((e) => e.source === sel.id).map((e) => e.label).filter(Boolean) : [];
  const closeFlowpathStudio = () => {
    const returnIndex = selected?.kind === 'edge' ? selected.index : null;
    setSelected(null);
    onFlowpathSelect?.(null);
    requestAnimationFrame(() => {
      svgRef.current?.querySelector<SVGGElement>(`[data-flowpath-index="${returnIndex}"]`)?.focus();
    });
  };
  const selectFlowpath = (index: number, label: string) => {
    setSelected({ kind: 'edge', index });
    onFlowpathSelect?.(label);
  };

  const minimapView = `0 0 ${laid.width} ${laid.height}`;
  const onCanvasPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (coordRef.current) coordRef.current.textContent = formatCoord(event.clientX - box.left, event.clientY - box.top);
  };
  return (
    <div ref={wrapRef} className={`topo-wrap${selectedEdge ? ' flowpath-split' : ''}`}>
      <div className="topo-toolbar" role="toolbar" aria-label={t('topology.toolbar')}>
        <button type="button" onClick={fitView}>{t('topo.fit')}</button>
        <button type="button" onClick={() => zoomBy(1 / 1.2)} aria-label={t('topo.zoomOut')}>−</button>
        <button type="button" onClick={() => zoomBy(1.2)} aria-label={t('topo.zoomIn')}>+</button>
        <button type="button" onClick={toggleFullscreen} aria-label={t('topo.fullscreen')} aria-pressed={isFullscreen}>⛶</button>
        <button type="button" onClick={() => setMinimapOpen((open) => !open)} aria-label={t('topo.minimap')} aria-pressed={minimapOpen}>▦</button>
        <span className="topo-toolbar-hint">{t('topology.hint')}</span>
      </div>
      {minimapOpen && (
        <svg className="topo-minimap" viewBox={minimapView} role="img" aria-label={t('topo.minimap')}>
          {laid.placed.map((n) => (
            <rect key={n.id} x={n.x} y={n.y} width={NODE_W} height={NODE_H} rx={0} />
          ))}
          <rect x={view.x} y={view.y} width={view.w} height={view.h} className="topo-minimap-view" />
        </svg>
      )}
      <div className={`topo-canvas${selectedEdge ? ' flowpath-split-canvas' : ''}`} onPointerMove={onCanvasPointer}>
        <FrameDecor />
        <span ref={coordRef} className="topo-coord" aria-hidden="true">{formatCoord(0, 0)}</span>
        {scanning && <div className="topo-scanner" aria-hidden="true" />}
        <svg
          ref={svgRef}
          className="topo-svg"
          style={{ '--topo-node-fs': `${labelFs}px` } as CSSProperties}
          viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
          onWheel={onWheel}
          onMouseDown={(e) => onDown(e)}
          onMouseMove={onMove}
          onMouseUp={onUp}
          onMouseLeave={onUp}
        >
          <defs>
            <marker id="topo-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" className="topo-arrowhead" />
            </marker>
          </defs>
          <TopologyEdgePaths
            edges={laid.edges}
            positions={pos}
            offsets={edgeOffsets}
            selectedIndex={selected?.kind === 'edge' ? selected.index : null}
            nodeWidth={NODE_W}
            nodeHeight={NODE_H}
            onSelect={selectFlowpath}
          />
          {laid.placed.map((n) => {
            const p = pos[n.id] || n;
            const junction = isJunction(n.kind);
            const isSelected = selected?.kind === 'node' && selected.id === n.id;
            return (
              <g
                key={n.id}
                data-node-id={n.id}
                transform={`translate(${p.x},${p.y})`}
                className={`topo-node ${junction ? 'is-node' : 'is-flowpath'}${isSelected ? ' selected' : ''}`}
                tabIndex={0}
                role="button"
                aria-label={t('workspace.inspectNode', { kind: n.kind, label: n.label })}
                aria-pressed={isSelected}
                onMouseDown={(e) => { e.stopPropagation(); onDown(e, n.id); }}
                onClick={(e) => {
                  e.stopPropagation();
                  if (!moved.current) {
                    setSelected({ kind: 'node', id: n.id });
                    onFlowpathSelect?.(null);
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key !== 'Enter' && e.key !== ' ') return;
                  e.preventDefault();
                  setSelected({ kind: 'node', id: n.id });
                  onFlowpathSelect?.(null);
                }}
              >
                <title>{n.label}</title>
                <rect width={NODE_W} height={NODE_H} rx={0} />
                <PixelIconInSvg name={kindIcon(n.kind)} x={6} y={NODE_H / 2 - 12} size={24} className="topo-node-icon" />
                <text x={36} y={NODE_H / 2 + 4} className="topo-node-label">{n.label}</text>
              </g>
            );
          })}
          <TopologyEdgeLabels
            edges={laid.edges}
            positions={pos}
            offsets={edgeOffsets}
            nodeWidth={NODE_W}
            nodeHeight={NODE_H}
            labelFontSize={labelFs}
            onSelect={selectFlowpath}
          />
        </svg>
        {selectedEdge && (
          <TopologyInspector
            selectedNode={null}
            selectedEdge={selectedEdge}
            inbound={[]}
            outbound={[]}
            flowpathDetails={flowpathDetails}
            flowpathLoading={flowpathLoading}
            flowpathError={flowpathError}
            onBack={closeFlowpathStudio}
          />
        )}
      </div>
      {(laid.edges.length > 0 || laid.placed.length > 0) && (
        <ul className="topo-touch-list" aria-label={t('workspace.touchList')}>
          {laid.edges.map((edge, index) => (
            <li key={`touch-edge-${index}`}>
              <button
                type="button"
                className="topo-touch-target"
                aria-pressed={selected?.kind === 'edge' && selected.index === index}
                onClick={() => selectFlowpath(index, edge.label)}
              >
                <span className="topo-touch-kind">{t('workspace.touchFlowpath')}</span>
                <span className="topo-touch-label">{edge.label || `${edge.source} → ${edge.target}`}</span>
              </button>
            </li>
          ))}
          {laid.placed.map((n) => (
            <li key={`touch-node-${n.id}`}>
              <button
                type="button"
                className="topo-touch-target"
                aria-pressed={selected?.kind === 'node' && selected.id === n.id}
                onClick={() => { setSelected({ kind: 'node', id: n.id }); onFlowpathSelect?.(null); }}
              >
                <span className="topo-touch-kind">{n.kind}</span>
                <span className="topo-touch-label">{n.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {!selectedEdge && (
        <TopologyInspector
          selectedNode={sel ?? null}
          selectedEdge={null}
          inbound={inbound}
          outbound={outbound}
          flowpathDetails={flowpathDetails}
          flowpathLoading={flowpathLoading}
          flowpathError={flowpathError}
        />
      )}
      <p className="topo-meta">
        {counts
          ? `${t(pickCountKey('workspace.node', counts.nodes) as 'workspace.node_one', { count: counts.nodes })} · ${t(pickCountKey('workspace.flowpath', counts.flowpaths) as 'workspace.flowpath_one', { count: counts.flowpaths })}`
          : t(pickCountKey('workspace.node', netNodes.length) as 'workspace.node_one', { count: netNodes.length })}
        {truncated ? ` · ${t('workspace.graphTruncated')}` : ''}
        {selectedEdge ? ` · ${t('workspace.graphStudioOpen')}` : ` · ${t('workspace.graphHint')}`}
      </p>
    </div>
  );
}
