import FlowpathDetailPanel from './FlowpathDetailPanel';
import type { NetEdge, NetNode } from './TopologyMap';
import { useLocale } from './i18n/index.ts';
import type { FlowpathDetails } from './workspaceApi';

type TopologyInspectorProps = {
  readonly selectedNode: NetNode | null;
  readonly selectedEdge: NetEdge | null;
  readonly inbound: readonly string[];
  readonly outbound: readonly string[];
  readonly flowpathDetails: FlowpathDetails | null;
  readonly flowpathLoading: boolean;
  readonly flowpathError: string;
  readonly onBack?: () => void;
};

export function TopologyInspector({
  selectedNode,
  selectedEdge,
  inbound,
  outbound,
  flowpathDetails,
  flowpathLoading,
  flowpathError,
  onBack,
}: TopologyInspectorProps) {
  const { t } = useLocale();
  if (!selectedNode && !selectedEdge) return null;

  return (
    <div className="topo-detail-host" data-testid="topology-inspector">
      {selectedNode && (
        <aside className="topo-detail">
          <p className="topo-detail-name">{selectedNode.label}</p>
          <p className="topo-detail-kind">{selectedNode.kind}</p>
          {inbound.length > 0 && <p className="topo-detail-row"><b>{t('workspace.inLabel')}</b> {inbound.join(', ')}</p>}
          {outbound.length > 0 && <p className="topo-detail-row"><b>{t('workspace.outLabel')}</b> {outbound.join(', ')}</p>}
          {inbound.length === 0 && outbound.length === 0 && <p className="topo-detail-kind">{t('workspace.noFlowpaths')}</p>}
        </aside>
      )}
      {selectedEdge && (
        <FlowpathDetailPanel
          label={selectedEdge.label}
          source={selectedEdge.source}
          target={selectedEdge.target}
          details={flowpathDetails}
          loading={flowpathLoading}
          error={flowpathError}
          onBack={onBack ?? (() => undefined)}
        />
      )}
    </div>
  );
}
