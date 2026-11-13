import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import * as resultPresentation from '../src/resultPresentation.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('series presenter returns a bounded semantic numeric table without source paths', () => {
  // Given: a server-bounded PT slice with units, lineage and an injected source path.
  const receipt = {
    variable: 'PT',
    units: { time: 's', value: 'bara' },
    position: 'SECTION:7',
    row_limit: 5,
    total_rows: 1_000,
    returned_rows: 5,
    rows: [
      { time: 0, value: 1.25 },
      { time: 1, value: 1.5 },
      { time: 2, value: 1.75 },
      { time: 3, value: 2 },
      { time: 4, value: 2.25 },
    ],
    time_range: { start: 0, end: 4 },
    source_sha256: 'a'.repeat(64),
    source_path: 'C:\\Users\\Jordan\\secret\\case.ppl',
    truncated: true,
    truncation: 'head',
    analysis: { minimum: 1.25, maximum: 2.25, mean: 1.75 },
  };

  // When: Chat prepares the receipt for its table component.
  const table = resultPresentation.presentSeriesTable(receipt);

  // Then: the table is bounded, semantic and contains no absolute source path.
  assert.deepEqual(table, {
    caption: 'PT at SECTION:7',
    time_header: 'Time (s)',
    value_header: 'PT (bara)',
    rows: receipt.rows,
    row_summary: '5 of 1,000 rows · head sample',
    analysis_summary: 'Min 1.25 · Max 2.25 · Mean 1.75',
    truncated: true,
  });
  assert.equal(JSON.stringify(table).includes('C:\\Users'), false);
});

test('artifact presenter derives actions from an opaque receipt and strips path-like filenames', () => {
  // Given: a current PNG receipt with every authenticated action.
  const receipt = {
    artifact_id: 'artifact_0123456789abcdef0123456789abcdef',
    kind: 'png',
    mime: 'image/png',
    size_bytes: 4_096,
    sha256: 'b'.repeat(64),
    suggested_filename: 'C:\\private\\pressure-profile.png',
    lineage: { source_id: 'run:run42/case.tpl' },
    workspace_generation: 7,
    actions: ['download', 'open_in_results', 'native_save_as'],
  };

  // When: Chat turns the wire receipt into a safe presentation.
  const presentation = resultPresentation.presentArtifactReceipt(receipt, 7);

  // Then: only the opaque identifier reaches actions and path segments do not render.
  assert.equal(presentation.receipt.suggested_filename, 'pressure-profile.png');
  assert.deepEqual(presentation.actions, [
    { kind: 'download', artifact_id: 'artifact_0123456789abcdef0123456789abcdef' },
    { kind: 'open-results', artifact_id: 'artifact_0123456789abcdef0123456789abcdef' },
    { kind: 'save-as', artifact_id: 'artifact_0123456789abcdef0123456789abcdef' },
  ]);
  assert.equal(JSON.stringify(presentation).includes('C:\\private'), false);
  assert.equal(JSON.stringify(presentation).includes('sandbox:'), false);
});

test('series presenter caps oversized receipts without overstating visible rows', () => {
  // Given: a valid server receipt at the 5,000-row wire limit.
  const rows = Array.from({ length: 600 }, (_, index) => ({ time: index, value: index / 10 }));

  // When: Chat prepares the receipt for the bounded DOM table.
  const table = resultPresentation.presentSeriesTable({
    variable: 'TM',
    units: { time: 's', value: 'degC' },
    position: null,
    total_rows: 600,
    returned_rows: 600,
    rows,
    truncated: false,
    truncation: 'head',
  });

  // Then: visible-row copy matches the actual bounded table.
  assert.equal(table.rows.length, 500);
  assert.equal(table.row_summary, '500 of 600 rows · UI-bounded sample');
  assert.equal(table.truncated, true);
});

test('series summaries resolve through t() keys in both locales', async () => {
  // Given: the same PT slice and a recording translator.
  const { translate } = await import('../src/i18n/index.ts');
  const receipt = {
    variable: 'PT',
    units: { time: 's', value: 'bara' },
    total_rows: 1_000,
    returned_rows: 5,
    rows: [
      { time: 0, value: 1.25 },
      { time: 1, value: 1.5 },
    ],
    truncated: true,
    truncation: 'head',
    analysis: { minimum: 1.25, maximum: 2.25, mean: 1.75 },
  };
  const seen = [];
  const recording = (key, vars) => {
    seen.push(key);
    return translate('en', key, vars);
  };

  // When: the table is presented with a translator.
  const table = resultPresentation.presentSeriesTable(receipt, undefined, recording);

  // Then: the summaries come from dictionary keys and read identically in en.
  assert.ok(seen.includes('series.rowSummary'), 'row summary key requested');
  assert.ok(seen.includes('series.rowSample'), 'row sample key requested');
  assert.ok(seen.includes('series.analysisSummary'), 'analysis summary key requested');
  assert.equal(table.row_summary, '2 of 1,000 rows · UI-bounded sample');
  assert.equal(table.analysis_summary, 'Min 1.25 · Max 2.25 · Mean 1.75');
  assert.equal(
    resultPresentation.presentSeriesTable(receipt, undefined, (key, vars) => translate('ko', key, vars)).row_summary,
    '1,000행 중 2행 · UI-bounded 샘플',
  );
});

test('historical artifact is read-only and cannot claim a cancelled Save As succeeded', async () => {
  // Given: an artifact from a prior workspace generation and the reusable Save As component.
  const receipt = {
    artifact_id: 'artifact_abcdef0123456789abcdef0123456789',
    kind: 'csv',
    mime: 'text/csv',
    size_bytes: 128,
    sha256: 'c'.repeat(64),
    suggested_filename: 'series.csv',
    lineage: { source_id: 'result_old' },
    workspace_generation: 3,
    actions: ['download', 'open_in_results', 'native_save_as'],
  };
  const saveAs = await read('../src/NativeSaveAsAction.tsx');
  const en = await read('../src/i18n/en.ts');

  // When: the receipt is presented in generation four.
  const presentation = resultPresentation.presentArtifactReceipt(receipt, 4);

  // Then: it is explicitly read-only and cancellation remains non-success.
  assert.deepEqual(presentation.actions, []);
  assert.equal(presentation.read_only, true);
  assert.match(saveAs, /result\.status === 'cancelled'/);
  assert.match(saveAs, /t\('saveas\.cancelledTitle'\)/);
  assert.match(en, /'saveas\.cancelledTitle': 'Save As cancelled'/);
  assert.doesNotMatch(saveAs, /result\.status === 'cancelled'[\s\S]{0,240}setSaved\(/);
});

test('artifact evidence detector accepts only the complete hash-bound wire receipt', () => {
  // Given: one complete receipt and one legacy presenter-only shape.
  const complete = {
    artifact_id: 'artifact_0123456789abcdef0123456789abcdef',
    kind: 'pdf',
    mime: 'application/pdf',
    size_bytes: 512,
    sha256: 'd'.repeat(64),
    suggested_filename: 'review.pdf',
    lineage: { source_kind: 'run', source_id: 'run:run42/case.tpl' },
    workspace_generation: 8,
    actions: ['download', 'open_in_results', 'native_save_as'],
  };
  const legacy = { ...complete, artifact_id: 'artifact_plot_1', actions: undefined };

  // When/Then: generic tool results cannot impersonate actionable artifacts.
  assert.equal(resultPresentation.isArtifactReceipt(complete), true);
  assert.equal(resultPresentation.isArtifactReceipt(legacy), false);
});

test('Chat artifact and series components use semantic controls without pseudo-links', async () => {
  // Given: the focused Chat evidence components and authenticated API adapter.
  const [artifact, series, evidence, api] = await Promise.all([
    read('../src/ArtifactCard.tsx'),
    read('../src/SeriesTable.tsx'),
    read('../src/EvidenceBlock.tsx'),
    read('../src/resultApi.ts'),
  ]);

  // When: their executable source contracts are inspected.
  // Then: table semantics and all three artifact actions are explicitly wired.
  assert.match(series, /<table\b/);
  assert.match(series, /<caption>/);
  assert.match(series, /<th[^>]*scope="col"/);
  assert.match(artifact, /<NativeSaveAsAction[^>]*artifact=\{`artifact:\$\{artifact\.artifact_id\}`\}/s);
  assert.match(artifact, /downloadArtifact\(artifact\.artifact_id/);
  assert.match(artifact, /requestOpenArtifactInResults\([\s\S]*artifactId: artifact\.artifact_id[\s\S]*resultId/s);
  assert.match(api, /apiFetch\(artifactDownloadUrl\(artifactId\)/);
  assert.match(evidence, /<SeriesTable[^>]*receipt=\{result\}/s);
  assert.match(evidence, /<ArtifactCard[^>]*receipt=\{result\}/s);
  for (const source of [artifact, series, evidence, api]) {
    assert.doesNotMatch(source, /sandbox:/);
  }
});

test('Open in Results emits only safe opaque artifact and result identities', async () => {
  // Given: a local event target standing in for the application shell.
  const navigation = await import('../src/artifactNavigation.ts');
  const target = new EventTarget();
  const received = [];
  target.addEventListener(navigation.OPEN_ARTIFACT_IN_RESULTS_EVENT, (event) => {
    received.push(event.detail);
  });

  // When: the artifact card requests navigation to its source result.
  navigation.requestOpenArtifactInResults({
    artifactId: 'artifact_0123456789abcdef0123456789abcdef',
    resultId: 'run:run42/case.tpl',
  }, target);

  // Then: the event contains the two safe IDs and no path-shaped data.
  assert.deepEqual(received, [{
    artifact_id: 'artifact_0123456789abcdef0123456789abcdef',
    result_id: 'run:run42/case.tpl',
  }]);
  assert.deepEqual(Object.keys(received[0]), ['artifact_id', 'result_id']);
});

test('Open in Results rejects traversal-shaped result identities', async () => {
  // Given: the event helper and result IDs that resemble paths rather than canonical identities.
  const navigation = await import('../src/artifactNavigation.ts');
  const target = new EventTarget();
  const invalidIds = [
    'workspace:../secret.tpl',
    'run:run42//case.tpl',
    'run:run42/./case.tpl',
    'C:\\private\\case.tpl',
    '/absolute/case.tpl',
    'workspace:C:/private/case.tpl',
    'run:C:/private/case.tpl',
    'workspace:a:b.tpl',
    `workspace:${'a'.repeat(4_097)}.tpl`,
  ];

  // When/Then: none can cross the application-navigation boundary.
  for (const resultId of invalidIds) {
    assert.throws(() => navigation.requestOpenArtifactInResults({
      artifactId: 'artifact_0123456789abcdef0123456789abcdef',
      resultId,
    }, target), /Invalid result_id/);
  }
});
