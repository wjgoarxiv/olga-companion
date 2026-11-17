import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readResultsSource } from './results-source.mjs';
import { readSessionSource } from './session-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('series, CSV, and publication APIs accept the same optional view specification', async () => {
  const api = await readSessionSource(import.meta.url);

  assert.match(api, /export interface SeriesViewSpec/);
  assert.match(api, /value_unit\?: string/);
  assert.match(api, /time_unit\?: string/);
  assert.match(api, /quantity_kind: QuantityKind/);
  assert.match(api, /range: SeriesRangeSpec/);
  assert.match(api, /fetchSeries\([\s\S]*view\?: SeriesViewSpec/);
  assert.match(api, /exportPublicationPlot\([\s\S]*view\?: SeriesViewSpec/);
  assert.match(api, /exportSelectedCsv\([\s\S]*view\?: SeriesViewSpec/);
  assert.ok((api.match(/\.\.\.\(view \? view : \{\}\)/g) || []).length >= 3, 'all result requests spread the same view fields');
});

test('ResultsView guards stale series and export responses and shares the chart view with exports', async () => {
  // The plot tab owns the rail, calibration rail and chart; the guard contract
  // spans the orchestrator and the tab module.
  const [results, plotTab] = await Promise.all([
    readResultsSource(import.meta.url),
    read('../src/ResultPlotTab.tsx'),
  ]);
  const sources = `${results}\n${plotTab}`;

  assert.match(sources, /requestRef/);
  assert.match(sources, /figureExportRequestRef/);
  assert.match(sources, /csvExportRequestRef/);
  assert.match(sources, /preferredSeriesView/);
  assert.match(sources, /<CalibrationRail/);
  assert.match(sources, /session\.fetchSeries\(selected\.id, variable\.variable, variable\.position, nextView\)/);
  assert.match(sources, /session\.exportPublicationPlot\(selected\.id, overlay\.activeVariable\.variable, overlay\.activeVariable\.position, overlay\.viewSpec\)/);
  assert.match(sources, /session\.exportSelectedCsv\(selected\.id, overlay\.activeVariable\.variable, overlay\.activeVariable\.position, overlay\.viewSpec\)/);
  assert.match(sources, /publication\.publication\.font_family/, 'the export receipt reports the backend-resolved portable font');
  assert.doesNotMatch(sources, /meta=\{`Pretendard/, 'the receipt never claims a font that was not embedded');
});

test('inventory refreshes are epoch-guarded and reconcile against the current selected id', async () => {
  const results = await readResultsSource(import.meta.url);

  assert.match(results, /import \{ createRequestEpoch \} from '\.\/requestEpoch'/);
  assert.match(results, /inventoryRequestRef/);
  assert.match(results, /selectedIdRef/);
  assert.match(results, /useRef\(createRequestEpoch\(\)\)/);
  assert.match(results, /const requestId = inventoryRequestRef\.current\.begin\(\)/);
  assert.match(results, /if \(!inventoryRequestRef\.current\.isCurrent\(requestId\)\) return/);
  assert.match(results, /const currentSelectedId = selectedIdRef\.current/);
  assert.match(results, /inventory\.results\.find\(\(result\) => result\.id === currentSelectedId\)/);
  assert.match(results, /async function openFile[\s\S]*inventoryRequestRef\.current\.invalidate\(\)[\s\S]*selectedIdRef\.current = f\.id/);
});

test('variable discovery reuses matching data and only fetches a nonmatching explicit view', async () => {
  const results = await read('../src/useResultSeriesOverlay.ts');
  const start = results.indexOf('async function toggleVariable');
  const end = results.indexOf('async function changeView', start);
  const pickVar = results.slice(start, end);

  assert.match(results, /discoveryMatchesPreferredView/);
  assert.match(pickVar, /discoveryMatchesPreferredView\(discovered, nextView\)/);
  assert.match(pickVar, /\? discovered\s*:\s*await session\.fetchSeries\(selected\.id, variable\.variable, variable\.position, nextView\)/s);
  assert.match(pickVar, /view: nextView/, 'exports retain the exact explicit preferred view even when discovery is reused');
});

test('view changes preserve accepted evidence until the current backend response is accepted', async () => {
  const results = await read('../src/useResultSeriesOverlay.ts');
  const start = results.indexOf('async function changeView');
  const end = results.indexOf('\n  return {', start);
  const changeView = results.slice(start, end);
  const requestIndex = changeView.indexOf('await session.fetchSeries');
  const seriesAcceptIndex = changeView.indexOf('setPlottedSeries(viewed)');
  const viewAcceptIndex = changeView.indexOf('view: itemView');
  const preferenceAcceptIndex = changeView.indexOf('persistPreferences(activeViewed.series)');

  assert.ok(start >= 0 && end > start);
  assert.doesNotMatch(changeView, /setPlottedSeries\(\[\]\)/, 'pending and rejected requests keep the accepted chart visible');
  assert.ok(requestIndex >= 0 && seriesAcceptIndex > requestIndex, 'series swaps only after the response');
  assert.ok(viewAcceptIndex > requestIndex, 'accepted request spec swaps only after the response');
  assert.ok(preferenceAcceptIndex > requestIndex, 'preferences are derived only from accepted backend metadata');
  assert.doesNotMatch(changeView.slice(0, requestIndex), /setUnitPreferences|saveUnitPreferences/, 'requested units are never persisted before acceptance');
  assert.match(changeView, /if \(!requestRef\.current\.isCurrent\(requestId\)\) return/);
});

test('390px results controls expose mobile 44px targets without horizontal overflow', async () => {
  const css = `${await read('../src/styles/results.css')}\n${await read('../src/styles/workbench-prompts.css')}\n${await read('../src/styles/controls.css')}`;
  const mobileStart = css.indexOf('@media (max-width: 760px)');
  const mobile = css.slice(mobileStart);

  assert.ok(mobileStart >= 0);
  for (const selector of ['\\.rv-var', '\\.rv-filter', '\\.rv-files-head \\.ui-button', '\\.workbench-prompt-footer \\.ui-button', '\\.result-export', '\\.receipt-actions a']) {
    assert.match(mobile, new RegExp(`${selector}\\s*\\{[^}]*min-height:\\s*44px`, 's'), `${selector} has a 44px mobile target`);
  }
  assert.match(mobile, /\.rv-main\s*\{[^}]*overflow-x:\s*hidden/s);
  assert.match(mobile, /\.result-analysis-actions\s*\{[^}]*max-width:\s*100%/s);
  assert.match(mobile, /\.result-downloads\s*\{[^}]*max-width:\s*100%/s);
});

test('trend surface is focusable, keyboard operable, announced, and uses bounded geometry lookup', async () => {
  const chart = await read('../src/TrendChart.tsx');

  assert.match(chart, /buildTrendGeometry/);
  assert.match(chart, /createNearestPointLookup/);
  assert.match(chart, /transitionInspection/);
  assert.match(chart, /finiteSampleOrdinal/);
  assert.match(chart, /tabIndex=\{0\}/);
  assert.match(chart, /transitionInspection\(event\.key, activeIndex, navigation\)/);
  assert.match(chart, /finiteSampleOrdinal\(activeIndex, navigation\)/);
  assert.doesNotMatch(chart, /activeIndex as number\) \+ 1/);
  assert.match(chart, /aria-live="polite"/);
  assert.doesNotMatch(chart, /role="img"/);
  assert.match(chart, /xTicks\.map\(\(tick, index\)/, 'the last tick is addressable');
  assert.match(chart, /textAnchor=\{index === xTicks\.length - 1 \? 'end' : 'middle'\}/, 'the last x tick anchors end so it never clips');
});
