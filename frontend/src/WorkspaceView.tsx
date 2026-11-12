import { useState, useEffect, useRef } from 'react';
import * as session from './session';
import TopologyMap from './TopologyMap';
import { createWorkspaceHydration } from './workspaceCaseOpen';
import { workspaceRootLabel } from './workspaceLabels';
import { Button } from './ui/Button';
import { ActivityLoader } from './ui/ActivityLoader';
import { OperationStatus } from './ui/OperationStatus';
import { createRequestEpoch } from './requestEpoch';
import { useLocale } from './i18n/index.ts';
import { WorkbenchPrompt } from './WorkbenchPrompt';
import { publishCaseProblems, resetCaseProblems, type CaseProblem } from './shell/caseProblems';
import { OPEN_TAB_PREVIEW_EVENT, parseTabPreviewEvent } from './shell/workspaceEvents';
import { consumeStagedTabPreview } from './shell/FluidTableFlow';

type WorkspaceViewProps = {
  readonly cases: session.WorkspaceCase[];
  readonly root: string;
  readonly activeCase: string | null;
  readonly onOpenSettings: () => void;
  readonly onNewCase?: () => void;
};

/** The Workspace view — a persistent case inspector. Pick a case from the file
 *  list and its network renders on a real topology canvas (not a chat evidence
 *  row). Surfaces genkey_topology outside the conversation. */
export default function WorkspaceView({
  cases,
  root,
  activeCase,
  onOpenSettings,
  onNewCase
}: WorkspaceViewProps) {
  const [selected, setSelected] = useState<string | null>(null); // tracked by rel
  const [topo, setTopo] = useState<session.Topology | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [flowpathDetails, setFlowpathDetails] = useState<session.FlowpathDetails | null>(null);
  const [flowpathLoading, setFlowpathLoading] = useState(false);
  const [flowpathError, setFlowpathError] = useState('');
  const [tabPreview, setTabPreview] = useState<session.TabPreview | null>(null);
  const [tabLoading, setTabLoading] = useState(false);
  const [tabError, setTabError] = useState('');
  const tabRequestRef = useRef(createRequestEpoch());
  const flowpathRequestRef = useRef(createRequestEpoch());
  const flowpathAbortRef = useRef<AbortController | null>(null);

  function clearFlowpathDetails() {
    flowpathAbortRef.current?.abort();
    flowpathAbortRef.current = null;
    flowpathRequestRef.current.invalidate();
    setFlowpathDetails(null);
    setFlowpathLoading(false);
    setFlowpathError('');
  }

  async function inspectFlowpath(flowpath: string | null) {
    if (!flowpath || !selected) {
      clearFlowpathDetails();
      return;
    }
    const request = flowpathRequestRef.current.begin();
    flowpathAbortRef.current?.abort();
    const controller = new AbortController();
    flowpathAbortRef.current = controller;
    setFlowpathDetails(null);
    setFlowpathError('');
    setFlowpathLoading(true);
    try {
      const details = await session.fetchFlowpathDetails(selected, flowpath, controller.signal);
      if (flowpathRequestRef.current.isCurrent(request) && details.flowpath === flowpath) setFlowpathDetails(details);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') return;
      if (flowpathRequestRef.current.isCurrent(request)) {
        setFlowpathError(cause instanceof Error ? cause.message : t('workspace.flowpathUnavailable') ?? 'Flowpath geometry is unavailable.');
      }
    } finally {
      if (flowpathRequestRef.current.isCurrent(request)) setFlowpathLoading(false);
    }
  }
  const hydrationRef = useRef<ReturnType<typeof createWorkspaceHydration> | null>(null);
  if (hydrationRef.current == null) {
    hydrationRef.current = createWorkspaceHydration(
      {
        activate: () => Promise.resolve(),
        fetchTopology: session.fetchTopology,
      },
      {
        onStart: (c) => {
          clearFlowpathDetails();
          setSelected(c.rel);
          setError('');
          setTopo(null);
          setLoading(true);
        },
        onSuccess: setTopo,
        onError: (cause) => setError(cause.message),
        onSettled: () => setLoading(false),
      },
    );
  }

  /** Preview a PVT table. Read-only: it never becomes the active case. */
  async function openTab(c: session.WorkspaceCase) {
    const requestId = tabRequestRef.current.begin();
    setSelected(c.rel);
    setTopo(null);
    setFlowpathDetails(null);
    setTabPreview(null);
    setTabError('');
    setTabLoading(true);
    try {
      const preview = await session.inspectTab(c.rel);
      if (!tabRequestRef.current.isCurrent(requestId)) return;
      setTabPreview(preview);
    } catch (cause) {
      if (!tabRequestRef.current.isCurrent(requestId)) return;
      setTabError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (tabRequestRef.current.isCurrent(requestId)) setTabLoading(false);
    }
  }

  useEffect(() => () => {
    hydrationRef.current?.invalidate();
    flowpathRequestRef.current.invalidate();
    flowpathAbortRef.current?.abort();
    resetCaseProblems();
  }, []);

  /** The shell Explorer previews .tab files without changing the active case.
      The banner stages the same request before navigating, so a remount also
      consumes it here; both paths clear the staged value exactly once. */
  useEffect(() => {
    const staged = consumeStagedTabPreview();
    if (staged !== null) {
      const target = cases.find((candidate) => candidate.rel === staged);
      if (target) void openTab(target);
    }
  }, [cases]);
  useEffect(() => {
    const onPreviewRequest = (event: Event) => {
      consumeStagedTabPreview();
      const rel = parseTabPreviewEvent(event);
      if (rel === null) return;
      const target = cases.find((candidate) => candidate.rel === rel);
      if (target) void openTab(target);
    };
    window.addEventListener(OPEN_TAB_PREVIEW_EVENT, onPreviewRequest);
    return () => window.removeEventListener(OPEN_TAB_PREVIEW_EVENT, onPreviewRequest);
  }, [cases]);

  const { t } = useLocale();
  /** Publish validation and PVT findings to the bottom Problems panel. */
  useEffect(() => {
    const problems: CaseProblem[] = [];
    for (const issue of tabPreview?.validation_errors ?? []) {
      problems.push({
        id: `pvt-error-${issue.rule_id ?? 'unknown'}-${issue.message ?? ''}`,
        severity: 'error',
        title: issue.message ?? t('workspace.unspecifiedIssue') ?? 'Unspecified validation issue',
        detail: issue.rule_id ? `[${issue.rule_id}] ${tabPreview?.path ?? ''}`.trim() : tabPreview?.path,
        source: 'pvt',
        nodeId: null,
      });
    }
    for (const issue of tabPreview?.validation_warnings ?? []) {
      problems.push({
        id: `pvt-warning-${issue.rule_id ?? 'unknown'}-${issue.message ?? ''}`,
        severity: 'warning',
        title: issue.message ?? t('workspace.unspecifiedIssue') ?? 'Unspecified validation issue',
        detail: issue.rule_id ? `[${issue.rule_id}] ${tabPreview?.path ?? ''}`.trim() : tabPreview?.path,
        source: 'pvt',
        nodeId: null,
      });
    }
    if (tabError !== '') {
      problems.push({ id: 'pvt-read', severity: 'error', title: tabError, source: 'pvt', nodeId: null });
    }
    if (error !== '') {
      problems.push({ id: 'topology-load', severity: 'error', title: error, source: 'topology', nodeId: null });
    }
    if (flowpathError !== '') {
      problems.push({ id: 'flowpath-load', severity: 'error', title: flowpathError, source: 'flowpath', nodeId: null });
    }
    publishCaseProblems(problems);
  }, [tabPreview, tabError, error, flowpathError, t]);

  const hydrationCase = cases.find((candidate) => (
    candidate.name === activeCase && candidate.suffix === '.genkey'
  ));
  const hydrationRel = hydrationCase?.rel ?? null;

  // Hydration is a setup-owned request. StrictMode cleanup invalidates its first
  // pass, and the replayed setup starts a fresh non-activating topology load.
  useEffect(() => {
    if (!hydrationCase) return;
    const setup = hydrationRef.current?.setup(hydrationCase);
    return setup?.cleanup;
  }, [hydrationRel]);
  const rootLabel = workspaceRootLabel(root);
  const caseCount = cases.filter((candidate) => candidate.suffix === '.genkey').length;
  const supportFileCount = cases.length - caseCount;

  return (
    <div className={`ws-view${cases.length === 0 ? ' empty' : !selected ? ' awaiting-selection' : ''}`}>
      <section className={'ws-canvas' + (!selected && cases.length === 0 ? ' empty' : '')}>
        {!selected && cases.length === 0 && (
          <WorkbenchPrompt
            className="ws-empty-state"
            kicker={t('workspace.emptyKicker') ?? 'Workspace 준비'}
            title={t('workspace.emptyTitle') ?? '사례가 아직 없습니다'}
            description={t('workspace.emptyDescription', { root: rootLabel }) ?? `원본 폴더를 정한 뒤 OLGA 사례나 PVT 테이블을 넣으세요. 목록은 ${rootLabel}에서 새로 읽습니다.`}
            contextLabel={t('workspace.emptyContextLabel') ?? '현재 목록'}
            contextValue={t('workspace.emptyList')}
            contextDetail={rootLabel}
          >
            <ol className="workbench-prompt-steps" aria-label={t('workspace.emptyStepsAria') ?? 'Workspace 다음 단계'}>
              <li><span>01</span><div><strong>{t('workspace.emptyStep1Title') ?? 'Workspace 정하기'}</strong><em>{t('workspace.emptyStep1Desc') ?? 'OLGA 모델이 있는 폴더를 고르세요.'}</em></div></li>
              <li><span>02</span><div><strong>{t('workspace.emptyStep2Title') ?? '사례 파일 넣기'}</strong><em>{t('workspace.emptyStep2Desc') ?? 'Workspace에 .genkey 사례나 .tab 테이블을 넣으세요.'}</em></div></li>
            </ol>
            <div className="workbench-prompt-footer">
              <Button variant="primary" onClick={onOpenSettings}>{t('workspace.openSettings') ?? '설정 열기'}</Button>
              {onNewCase && <Button variant="secondary" onClick={onNewCase}>{t('workspace.emptyNewCase') ?? '새 케이스 만들기'}</Button>}
              <span className="workbench-prompt-note">{t('workspace.emptyNote') ?? '폴더가 바뀌면 목록을 다시 읽습니다.'}</span>
            </div>
          </WorkbenchPrompt>
        )}
        {!selected && cases.length > 0 && (
          <WorkbenchPrompt
            className="ws-selection-state"
            kicker={t('workspace.pickKicker') ?? 'Workspace 목록'}
            title={caseCount > 0 ? t('workspace.pickTitleCase') ?? '검사할 사례 고르기' : t('workspace.pickTitleNone') ?? 'OLGA 사례가 없습니다'}
            description={caseCount > 0
              ? t('workspace.pickDescCase') ?? '.genkey 파일을 목록에서 고르면 네트워크와 토폴로지, FLOWPATH 형상을 엽니다.'
              : t('workspace.pickDescSupport') ?? '지원 파일은 있지만, 토폴로지를 보려면 .genkey 사례가 필요합니다.'}
            contextLabel={t('workspace.pickContextLabel') ?? '고를 수 있는 목록'}
            contextValue={t('workspace.pickContextValue', { case: caseCount.toLocaleString(), support: supportFileCount.toLocaleString() }) ?? `${caseCount.toLocaleString()}건 사례 · ${supportFileCount.toLocaleString()}건 지원 파일`}
            contextDetail={caseCount > 0 ? t('workspace.pickContextDetailCase') ?? '.genkey 파일을 골라 시작하세요' : t('workspace.pickContextDetailNone') ?? '.genkey 파일을 넣어 시작하세요'}
          />
        )}
        {selected && (
          <header className="ws-canvas-head">
            <span className="ws-canvas-name">{selected.split('/').pop()}</span>
          </header>
        )}
        {loading && <ActivityLoader className="ws-loading" loadingLabel="Parsing network…" />}
        {error && <OperationStatus className="ws-operation-status" tone="error" title={t('workspace.errorTitle') ?? 'Case could not be opened'} detail={error} />}
        {tabLoading && <ActivityLoader className="ws-loading" loadingLabel={t('workspace.readingPvt') ?? 'Reading PVT table…'} />}
        {tabError && <OperationStatus className="ws-operation-status" tone="error" title={t('workspace.pvtUnreadableTitle') ?? 'PVT table could not be read'} detail={tabError} />}
        {tabPreview && (
          <section className="ws-tab-preview" aria-label={t('workspace.pvtPreviewAria') ?? 'PVT table preview'}>
            <OperationStatus
              className="ws-operation-status"
              tone={tabPreview.valid ? 'success' : 'info'}
              title={tabPreview.valid ? t('workspace.pvtReadableTitle') ?? 'PVT table is readable' : t('workspace.pvtIssueTitle') ?? 'PVT table reported issues'}
              detail={tabPreview.valid
                ? t('workspace.pvtReadableDetail') ?? 'Parsed and validated read-only; the source file is unchanged.'
                : t('workspace.pvtIssueDetail', { errors: (tabPreview.validation_errors ?? []).length, warnings: (tabPreview.validation_warnings ?? []).length }) ?? `${(tabPreview.validation_errors ?? []).length} error(s), ${(tabPreview.validation_warnings ?? []).length} warning(s).`}
            />
            {(tabPreview.validation_errors ?? []).length > 0 && (
              <ul className="ws-tab-issues">
                {(tabPreview.validation_errors ?? []).map((issue, index) => (
                  <li key={`${issue.rule_id ?? 'issue'}-${index}`}>
                    {issue.rule_id ? `[${issue.rule_id}] ` : ''}{issue.message ?? t('workspace.unspecifiedIssue') ?? 'Unspecified validation issue'}
                  </li>
                ))}
              </ul>
            )}
            <pre className="ws-tab-summary">{tabPreview.summary_text.trim()}</pre>
          </section>
        )}
        {topo && (
          <TopologyMap
            nodes={topo.nodes}
            edges={topo.edges}
            counts={topo.counts}
            truncated={topo.truncated}
            flowpathDetails={flowpathDetails}
            flowpathLoading={flowpathLoading}
            flowpathError={flowpathError}
            scanning={loading || tabLoading}
            onFlowpathSelect={(flowpath) => { void inspectFlowpath(flowpath); }}
          />
        )}
      </section>
    </div>
  );
}
