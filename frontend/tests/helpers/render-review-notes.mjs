import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { rolldown } from 'rolldown';

const src = (p) => fileURLToPath(new URL(`../../src/${p}`, import.meta.url));
const ENTRY = 'review-notes-render-entry';

const entrySource = `
import React, { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ChartUnitBar from ${JSON.stringify(src('ChartUnitBar.tsx'))};
import { ReviewedChangeItem } from ${JSON.stringify(src('CaseEditTable.tsx'))};
import { FluidFreshnessFacts } from ${JSON.stringify(src('FluidFreshness.tsx'))};
import { CaseLintList, KeywordCoverageMap } from ${JSON.stringify(src('CaseChecks.tsx'))};
import { RunFailurePanel } from ${JSON.stringify(src('RunFailurePanel.tsx'))};
import { CaseDiffResult } from ${JSON.stringify(src('CaseCompare.tsx'))};
import { CrossRunPicker } from ${JSON.stringify(src('CrossRunPicker.tsx'))};
import { CapabilityReason, capabilityReason } from ${JSON.stringify(src('EnvDrawer.tsx'))};
import { ko as KO_STRINGS } from ${JSON.stringify(src('i18n/ko.ts'))};
import { VersionMatrix, SupportText } from ${JSON.stringify(src('SupportInfo.tsx'))};
import TrendChart from ${JSON.stringify(src('TrendChart.tsx'))};
import { TrendDataTable } from ${JSON.stringify(src('TrendDataTable.tsx'))};
import { ambiguousGuide } from ${JSON.stringify(src('SweepParameterPicker.tsx'))};
import SweepSummaryTable from ${JSON.stringify(src('SweepSummaryTable.tsx'))};
import { RunSweepStatus, sweepPreviewRunnable as runnable } from ${JSON.stringify(src('RunSweepStatus.tsx'))};
export const sweepPreviewRunnable = runnable;
import { AiToolRow } from ${JSON.stringify(src('AiToolsPanel.tsx'))};
import { TutorialResumeChip } from ${JSON.stringify(src('TutorialSpotlight.tsx'))};
import { setLocale, translate } from ${JSON.stringify(src('i18n/index.ts'))};

export function sweepAmbiguousGuide(locale, names) {
  return ambiguousGuide((key, vars) => translate(locale, key, vars), names);
}

React.useSyncExternalStore = (_subscribe, getSnapshot) => getSnapshot();

export function renderUnitBar(locale, series) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(ChartUnitBar, {
    series, view: { quantity_kind: 'point' }, valueLabel: 'PT', disabled: false, onChange: () => {},
  }));
}

export function renderFluidFreshness(locale, rows) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(FluidFreshnessFacts, { rows }));
}

export function renderLint(locale, warnings) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(CaseLintList, { warnings }));
}

export function renderCoverage(locale, coverage) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(KeywordCoverageMap, { coverage }));
}

export function renderFailedRun(locale, stopReason, failure = null, props = {}, outputs = []) {
  setLocale(locale);
  const status = {
    run_id: 'run-1', state: 'failed', exit_code: 65, elapsed_ms: 1000, log_tail: '', outputs,
    source_name: 'case.genkey', stop_reason: stopReason, failure,
  };
  return renderToStaticMarkup(createElement(RunFailurePanel, { status, ...props }));
}

export function renderSweepSummary(locale, rows, initialSort) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(SweepSummaryTable, { rows, initialSort }));
}

export function renderSweepPreview(locale, preview) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(RunSweepStatus, { preview, status: null }));
}

export function renderCaseDiff(locale, diff) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(CaseDiffResult, { diff }));
}

export function renderCrossRunPicker(locale, runs, variable) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(CrossRunPicker, { runs, variable, disabled: false, onPick: () => {} }));
}

export function envReason(locale, cap) {
  return capabilityReason(cap, (key, vars) => translate(locale, key, vars), (key) => Object.prototype.hasOwnProperty.call(KO_STRINGS, key));
}

export function renderSupportText(locale, bundle) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(SupportText, { bundle }));
}

export function renderVersionMatrix(locale, rows) {
  setLocale(locale);
  return renderToStaticMarkup(React.createElement(VersionMatrix, { rows }));
}

export function renderCapabilityReason(locale, cap) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(CapabilityReason, { cap }));
}

export function renderTrendChart(series, overlays) {
  setLocale('en');
  return renderToStaticMarkup(createElement(TrendChart, { series, overlays, unit: 'bara' }));
}

export function renderTrendTable(locale, series, unit) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(TrendDataTable, { series, unit, id: 'tt' }));
}

export function renderTrendChartIn(locale, series) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(TrendChart, { series, unit: 'bara' }));
}

export function renderAiToolRow(locale, tool, outcome = null) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(AiToolRow, { tool, outcome, busy: false, onConnect: () => {}, onRemove: () => {} }));
}

export function renderResumeChip(locale, index, total) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(TutorialResumeChip, { index, total, onResume: () => {} }));
}

export function renderReviewedChange(locale, change) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(ReviewedChangeItem, { change }));
}
`;

let rendererPromise;

export function reviewNotesRenderer() {
  rendererPromise ??= (async () => {
    const bundle = await rolldown({
      input: ENTRY,
      platform: 'node',
      plugins: [{
        name: 'review-notes-entry',
        resolveId: (id) => (id === ENTRY ? `\0${ENTRY}` : id.endsWith('.css') ? '\0css-stub' : null),
        load: (id) => (id === `\0${ENTRY}` ? entrySource : id === '\0css-stub' ? 'export {};' : null),
      }],
      resolve: { extensions: ['.tsx', '.ts', '.mjs', '.js'] },
      transform: { define: { 'process.env.NODE_ENV': '"production"' } },
    });
    const { output } = await bundle.generate({ format: 'esm' });
    const dir = await mkdtemp(join(tmpdir(), 'review-notes-'));
    const file = join(dir, 'render.mjs');
    await writeFile(file, output[0].code);
    return import(pathToFileURL(file).href);
  })();
  return rendererPromise;
}
