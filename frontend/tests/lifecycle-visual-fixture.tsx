import React from 'react';
import { createRoot } from 'react-dom/client';
import '../src/styles.css';
import './lifecycle-visual-fixture.css';
import ApprovalCard from '../src/ApprovalCard';
import ArtifactCard from '../src/ArtifactCard';
import EvidenceBlock from '../src/EvidenceBlock';
import LifecycleEvidence from '../src/LifecycleEvidence';
import PipeTableDraftCard from '../src/PipeTableDraftCard';
import { presentPipeDraft } from '../src/pipeTableDraft.ts';
import Markdown from '../src/Markdown';
import MessageActions from '../src/MessageActions';
import SeriesTable from '../src/SeriesTable';
import TrendChart from '../src/TrendChart';
import { OperationStatus } from '../src/ui/OperationStatus';

const hashA = 'a'.repeat(64);
const hashB = 'b'.repeat(64);
const noop = () => undefined;

const caseSpec = {
  valid: true,
  publishable: false,
  spec_hash: hashA,
  compiled_hash: hashB,
  companion_status: 'verified',
  source_mutated: false,
  topology: {
    nodes: [{ label: 'INLET', kind: 'source' }, { label: 'TEE', kind: 'junction' }, { label: 'OUTLET', kind: 'sink' }],
    edges: [{ from: 'INLET', to: 'TEE', flowpath: 'FLOWPATH_WITH_A_LONG_ENGINEERING_IDENTIFIER' }, { from: 'TEE', to: 'OUTLET', flowpath: 'EXPORT' }],
  },
  geometry: [
    { flowpath: 'FLOWPATH_WITH_A_LONG_ENGINEERING_IDENTIFIER', pipe: 'P1_LONG_HORIZONTAL_SECTION', diameter_m: 0.0737, sections: 24 },
    { flowpath: 'EXPORT', pipe: 'P2_VERTICAL_RISER', diameter_m: 0.0493, sections: 9 },
  ],
  section_count: 33,
  validation: { clean: true, parser_clean: true, validator_clean: true, diagnostics: [] },
  warnings: [{ code: 'review_pvt', message: 'PVT companion is verified but remains bound to this reviewed transaction.' }],
  errors: [],
};

const editPlan = {
  publishable: true,
  semantic_diff: [
    { path: 'flowpaths.FLOWPATH_WITH_A_LONG_ENGINEERING_IDENTIFIER.pipes.P2_VERTICAL_RISER.diameter_m', before: 0.0493, after: 0.0612 },
    { path: 'integration.endtime_s', before: 3600, after: 7200 },
  ],
  text_diff: ['- DIAMETER=0.0493', '+ DIAMETER=0.0612'],
  transaction_id: 'transaction_reviewed_01',
  source_hash: hashA,
  compiled_hash: hashB,
  context_generation: 12,
};

const patrolSuccess = {
  state: 'completed', terminal: true, poll_count: 14, elapsed_ms: 9200,
  observations: [{ vendor_percent: 100, simulation_time_s: 7200, step: 9910, phase: 'Terminal', liveness: 'Process terminal' }],
};
const patrolFailure = {
  state: 'failed', terminal: true, poll_count: 5, elapsed_ms: 3400,
  observations: [{ vendor_percent: 42.5, simulation_time_s: 3060, step: 1812, phase: 'Solver', liveness: 'Process terminal' }],
  diagnosis: { reason: 'Minimum pressure violation near SECTION:27; review boundary conditions.' },
  proposal: { requires_fresh_approval: true },
};
const patrolRunning = {
  run_id: 'run-live-01', state: 'running', terminal: false, poll_count: 6, elapsed_ms: 4100,
  observations: [{ vendor_percent: 42.5, simulation_time_s: 3060, step: 1812, phase: 'running', liveness: 'supervised' }],
};

const draftMissingDiameter = presentPipeDraft('pipe_table_import', {
  created: false,
  issue_count: 2,
  issues: [
    { row: 4, field: 'diameter_m', reason: 'value is missing', code: 'value_missing', params: { field: 'diameter_m' } },
    { row: 4, field: 'roughness_m', reason: 'value is missing', code: 'value_missing', params: { field: 'roughness_m' } },
  ],
});
if (!draftMissingDiameter) throw new Error('Draft missing-diameter fixture is empty.');

const draftBrokenTable = presentPipeDraft('pipe_table_import', {
  created: false,
  issue_count: 2,
  issues: [
    { row: null, field: 'flowpath', reason: 'the table has no pipe rows', code: 'no_pipe_rows', params: {} },
    { row: null, field: 'caps', reason: 'the table is larger than a case can hold: nodes, sections', code: 'table_over_caps', params: { caps: ['nodes', 'sections'] } },
  ],
});
if (!draftBrokenTable) throw new Error('Draft broken-table fixture is empty.');

const seriesReceipt = {
  variable: 'PT', position: 'SECTION:27', units: { time: 's', value: 'bara' },
  rows: Array.from({ length: 8 }, (_, index) => ({ time: index * 900, value: 1.2 + index * 0.17 })),
  returned_rows: 8, total_rows: 24000, truncated: true, truncation: 'uniform',
  analysis: { minimum: 1.2, maximum: 2.39, mean: 1.795 },
};

const genkeyReview = {
  path: `path-sha256:${hashA}`,
  valid: true,
  validation: {
    script: 'genkey_validator.py',
    exit_code: 0,
    stdout: 'Validation Report: demo_bilge_partialwet_vent.genkey\nErrors: 0\nWarnings: 0',
  },
  topology: {
    script: 'topology_visualizer.py',
    exit_code: 0,
    stdout: 'Network Topology\nBILGELINE_UP → VENT_TEE → BILGELINE_DOWN',
  },
};

const pvtInspection = {
  valid: true,
  summary_text: [
    'PVT Table Summary: demo_water_air_evap.tab',
    '  Label:          demo_water_air_evap',
    '  Phase:          THREE',
    '  Formulation:    (none)',
    '  Components:  H2O (50.0 mol%), N2 (39.5 mol%), O2 (10.5 mol%)',
    '  Mol Weights: H2O=18.0152, N2=28.0135, O2=31.9988',
    '  Pressure:    0.01325 - 14.0132 bar (50 points)',
    '  Temperature: -236.035 - -143.968 C (bubble range)',
    '  Mesh Type:   STANDARD',
    '  File Size:   421.4 KB',
  ].join('\n'),
  validation_errors: [],
  validation_warnings: [],
};

const chartSeries = [{
  key: 'PT:SECTION:27',
  variable: { index: 0, variable: 'PT', position: 'SECTION:27', unit: 'bara', description: 'Pressure' },
  series: {
    variable: 'PT', unit: 'bara', description: 'Pressure', position: 'SECTION:27', time_unit: 's',
    time: [0, 900, 1800, 2700, 3600, 4500, 5400, 6300, 7200],
    values: [1.2, 1.33, 1.48, 1.71, 1.64, 1.92, 2.04, 2.22, 2.39],
    analysis: { scope: 'descriptive', samples: 9, start_time: 0, end_time: 7200, minimum: 1.2, maximum: 2.39, mean: 1.77, initial: 1.2, final: 2.39, delta: 1.19, percent_change: 99.2, peak_time: 7200, direction: 'increasing' },
    view: {
      value_conversion: { status: 'identity', source_unit: 'bara', requested_unit: 'bara', output_unit: 'bara', dimension: 'pressure', quantity_kind: 'point', reason: null },
      time_conversion: { status: 'identity', source_unit: 's', requested_unit: 's', output_unit: 's', dimension: 'time', quantity_kind: 'point', reason: null },
      range: { mode: 'full', samples: 9 },
    },
  },
  view: { value_unit: 'bara', time_unit: 's', quantity_kind: 'point', range: { mode: 'full' } },
  color: '#0067a8',
}];

function Card({ title, state, wide = false, children }: { title: string; state: string; wide?: boolean; children: React.ReactNode }) {
  return <section className={`qa-card ${wide ? 'qa-wide' : ''}`} data-qa-state={state}><h2>{title}</h2>{children}</section>;
}

function Fixture() {
  const requestedWidth = Number(new URLSearchParams(window.location.search).get('width'));
  const matrixWidth = Number.isFinite(requestedWidth) && requestedWidth >= 320 ? requestedWidth : undefined;
  const shellWidth = matrixWidth ? matrixWidth - (matrixWidth <= 720 ? 20 : 32) : undefined;
  return (
    <main className={`qa-shell ${matrixWidth && matrixWidth <= 720 ? 'qa-mobile' : ''}`} style={shellWidth ? { width: `${shellWidth}px`, maxWidth: 'none', marginInline: matrixWidth && matrixWidth <= 720 ? '10px' : '16px' } : undefined}>
      <header className="qa-head"><span className="eyebrow">RENDERED COMPONENT MATRIX</span><h1>Chat lifecycle evidence</h1><p>Production components · bounded receipts · responsive overflow probes</p></header>
      <div className="qa-grid">
        <Card title="Chat reply · resolved motion" state="assistant-message" wide>
          <div className="qa-chat-stage">
            <div className="msg assistant">
              <div className="bubble assistant"><Markdown text="Managed run launched. The approved `run_execute` request is now **running** with evidence-bound supervision." /></div>
              <MessageActions text="Managed run launched." onRetry={noop} showRetry />
            </div>
          </div>
        </Card>
        <Card title="Operation feedback · rounded" state="operation-status" wide>
          <OperationStatus tone="info" title="Approval request resolved" detail="run_execute is closed." />
        </Card>
        <Card title="GENKEY review · decision first" state="genkey-review" wide><EvidenceBlock name="genkey_review" result={genkeyReview} /></Card>
        <Card title="PVT inspection · engineering ledger" state="pvt-inspection" wide><EvidenceBlock name="fluids_inspect_tab" result={pvtInspection} /></Card>
        <Card title="CaseSpec · compiled" state="casespec"><LifecycleEvidence name="case_spec_compile" result={caseSpec} /></Card>
        <Card title="Reviewed semantic diff" state="edit-plan"><LifecycleEvidence name="case_edit_plan" result={editPlan} /></Card>
        <Card title="Patrol · completed" state="patrol-success"><LifecycleEvidence name="run_patrol" result={patrolSuccess} /></Card>
        <Card title="Patrol · failed with proposal" state="patrol-failure"><LifecycleEvidence name="run_patrol" result={patrolFailure} /></Card>
        <Card title="Patrol · running, still watched" state="patrol-running"><LifecycleEvidence name="run_patrol" result={patrolRunning} /></Card>
        <Card title="Pipe draft · missing diameter" state="draft-missing-diameter"><PipeTableDraftCard view={draftMissingDiameter} /></Card>
        <Card title="Pipe draft · broken table" state="draft-broken-table"><PipeTableDraftCard view={draftBrokenTable} /></Card>
        <Card title="Run approval · server-reviewed" state="run-approval" wide>
          <ApprovalCard request={{ name: 'run_execute', call_id: 'call_01', pending_id: 'pending_01', args: { source: 'model-value-is-not-rendered.genkey', selection_id: 'model-value-is-not-rendered' }, display: { case: 'demo_bilge_partialwet_vent.genkey', selection_id: 'selection_server_reviewed_0123456789', runtime_id: 'olga-2022.1-direct', executable: 'OLGA-2022.1.0.exe', output_target: 'managed-run-sandbox', source_sha256: hashA, timeout_s: 3600, context_generation: 12 } }} onApprove={noop} onRecover={noop} onReject={noop} pending={false} resolved={false} />
        </Card>
        <Card title="Bounded result table" state="series-table"><SeriesTable receipt={seriesReceipt} /></Card>
        <Card title="Authenticated artifact receipt" state="artifact"><ArtifactCard receipt={{ artifact_id: 'artifact_0123456789abcdef0123456789abcdef', kind: 'png', mime: 'image/png', size_bytes: 4096, sha256: hashB, suggested_filename: 'pressure-profile.png', lineage: { source_id: 'result_01' }, workspace_generation: 12, actions: ['download', 'open_in_results'] }} currentWorkspaceGeneration={12} /></Card>
        <Card title="Interactive result plot" state="plot" wide><TrendChart series={chartSeries[0].series} overlays={[]} unit="bara" /></Card>
      </div>
    </main>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Visual fixture root is missing.');
createRoot(rootElement).render(<Fixture />);
