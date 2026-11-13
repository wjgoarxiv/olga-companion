import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import test from 'node:test';
import { SESSION_SOURCE_FILES } from './session-source.mjs';

const EXPECTED_SESSION_EXPORTS = [
  'ActiveCase',
  'ApprovalExecution',
  'ArtifactDownloadError',
  'ArtifactKind',
  'ArtifactMime',
  'ArtifactReceipt',
  'ArtifactReceiptAction',
  'ChatSeriesReceipt',
  'ChatSeriesRow',
  'ConversionMetadata',
  'CsvExport',
  'FlowpathDetails',
  'FlowpathPipe',
  'FluidDraftComponent',
  'FluidDraftInput',
  'FluidDraftPreview',
  'FluidOpenResult',
  'FluidPickupResult',
  'LoadedResult',
  'NativeContextDialogResult',
  'NativeDialogCancelResult',
  'NativeDialogTerminal',
  'NativeSaveAsResult',
  'NativeSelectedContext',
  'OlgaCandidate',
  'OlgaDetection',
  'OlgaDetectionEvidence',
  'OlgaSelectionStatus',
  'Profile',
  'PublicationExport',
  'QuantityKind',
  'ResultFile',
  'ResultImageError',
  'ResultLineage',
  'ResultVar',
  'RunFailure',
  'RunOutput',
  'RunPreview',
  'RunStatus',
  'SaveAsRecoveryError',
  'SaveAsRecoveryStatus',
  'Series',
  'SeriesAnalysis',
  'SeriesRangeSpec',
  'SeriesViewMetadata',
  'SeriesViewSpec',
  'SessionMeta',
  'SolverProgress',
  'SweepCaseStatus',
  'SweepStatus',
  'TabPreview',
  'Topology',
  'WorkspaceCase',
  'WorkspaceContext',
  'artifactDownloadUrl',
  'cancelNativeDialog',
  'chooseNativeWorkspace',
  'deleteSession',
  'downloadArtifact',
  'executeApproval',
  'exportProfileCsv',
  'exportProfilePlot',
  'exportPublicationPlot',
  'exportSelectedCsv',
  'fetchActiveCase',
  'fetchFlowpathDetails',
  'fetchHealth',
  'fetchProfile',
  'fetchProviders',
  'fetchResultImage',
  'fetchResults',
  'fetchRunHistory',
  'fetchSaveAsRecoveryStatus',
  'fetchSeries',
  'fetchSessionHistory',
  'fetchSessionToken',
  'fetchSessions',
  'fetchTopology',
  'fetchWorkspace',
  'fetchWorkspaceContext',
  'fluidsDraftPreview',
  'fluidsOpenMultiflash',
  'fluidsPickupTab',
  'inspectTab',
  'loadResultVars',
  'newSession',
  'openNativeCase',
  'rejectApproval',
  'resultDownloadUrl',
  'resumeApproval',
  'runCancel',
  'runDetect',
  'runExecute',
  'runPreview',
  'runStatus',
  'saveArtifactAs',
  'setActiveCase',
  'stopChatResponse',
  'streamChat',
  'sweepCancel',
  'sweepExecute',
  'sweepPreview',
  'sweepStatus',
];

function pureLines(source) {
  return source
    .split('\n')
    .filter((line) => line.trim() && !line.trimStart().startsWith('//')).length;
}

test('session client is a stable facade over cohesive bounded modules', async () => {
  const modules = await Promise.all(
    SESSION_SOURCE_FILES.map(async (path) => ({
      path,
      source: await readFile(new URL(path, import.meta.url), 'utf8'),
    })),
  );

  for (const { path, source } of modules) {
    assert.ok(pureLines(source) <= 250, `${path} has ${pureLines(source)} pure lines; expected at most 250`);
  }

  const facade = modules[0].source;
  assert.doesNotMatch(facade, /^export (?:async function|function|class|interface)\b|^export type [A-Za-z_$]/m);
  const publicNames = [...facade.matchAll(/export(?: type)?\s*\{([^}]*)\}\s*from/g)]
    .flatMap((match) => match[1].split(',').map((name) => name.trim()).filter(Boolean))
    .sort();
  assert.deepEqual(publicNames, EXPECTED_SESSION_EXPORTS);
  for (const moduleName of [
    'sessionResponse',
    'sessionTransport',
    'chatSessionApi',
    'workspaceApi',
    'nativeDialogApi',
    'resultContracts',
    'resultApi',
    'runContracts',
    'runApi',
    'sweepApi',
  ]) {
    assert.match(facade, new RegExp(`from './${moduleName}'`));
  }
});
