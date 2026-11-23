import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('variable picker searches with formatted units and positions, 80 at a time', async () => {
  const picker = await read('../src/VariablePicker.tsx');
  assert.match(picker, /type="search"/, 'one search box filters variables');
  assert.match(picker, /formatUnit/, 'units render formatted, codes stay raw');
  assert.match(picker, /show-more|showMore/i, 'the 80 cap gets a show-more path');
  assert.match(picker, /aria-activedescendant|role="listbox"/, 'keyboard users can move through options');
  assert.match(picker, /aria-selected/, 'plotted state stays visible per option');
});

test('auto-plot fills the graph on fresh variables without touching payloads', async () => {
  const [overlay, plot] = await Promise.all([
    read('../src/useResultSeriesOverlay.ts'),
    read('../src/ResultPlotTab.tsx'),
  ]);
  assert.match(overlay, /pickAutoPlotVariable/, 'overlay owns the auto-plot choice');
  assert.match(overlay, /ensureAutoPlot/, 'overlay exposes one guarded auto-plot entry');
  assert.match(plot, /ensureAutoPlot\(variables\)/, 'fresh trend variables trigger one auto-plot');
  assert.match(overlay, /void toggleVariable\(choice\)/, 'trend auto-plot reuses the toggle path');
  assert.match(plot, /pickAutoPlotVariable\(variables\)/, 'fresh profile variables use the same pressure-first choice');
  assert.match(plot, /void pickVar\(choice\)/, 'profile auto-plot routes through the branch-aware pick path');
  assert.match(plot, /attempt\.vars !== variables/, 'a refetched variable list re-arms profile auto-plot on reselect');
});

test('trend chart zooms by brush, resets, and reads out with units', async () => {
  const [chart, layout] = await Promise.all([
    read('../src/TrendChart.tsx'),
    read('../src/ResultsLayout.tsx'),
  ]);
  assert.match(chart, /onBrushRange|brush/i, 'drag selects a time window');
  assert.match(chart, /niceTicks/, 'axes use nice ticks');
  assert.match(chart, /readout|Readout/i, 'hover shows a crosshair readout');
  assert.match(chart, /formatUnit/, 'the readout carries a formatted unit');
  assert.match(chart, /pathLength/, 'series draw in without measuring length');
  assert.match(layout, /bounds/, 'brush commits a bounded view range');
  assert.match(layout, /resetBrush|brushReset|range.*full/i, 'zoom resets to full');
});

test('profile chart titles its y-axis with the formatted unit', async () => {
  const [chart, ko, en] = await Promise.all([
    read('../src/ProfileChart.tsx'),
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
  ]);
  assert.match(chart, /niceTicks/, 'profile axes use nice ticks');
  assert.match(chart, /formatUnit/, 'axis titles carry formatted units');
  assert.match(chart, /<text[^>]*className="profile-y-title"|y-axis|yTitle/i, 'the y-axis has a title element');
  assert.ok(ko.includes(`'profile.yAxis':`) && en.includes(`'profile.yAxis':`), 'y-axis title is translated');
});

test('series table virtualises long traces with formatted units', async () => {
  const [table, presentation] = await Promise.all([
    read('../src/SeriesTable.tsx'),
    read('../src/resultPresentation.ts'),
  ]);
  assert.match(presentation, /seriesTableWindow/, 'windowing maths live in the presentation module');
  assert.match(table, /seriesTableWindow|aria-rowcount|overscan/i, 'the table renders a window, not every row');
  assert.match(table, /formatUnit/, 'headers carry formatted units');
});

test('series table headers name each unit once with formatted casing', async () => {
  const table = await read('../src/SeriesTable.tsx');
  assert.match(table, /function displayHeader\(header: string, rawUnit: string\)/, 'header swap is an explicit helper');
  assert.match(table, /header\.endsWith\(` \(\$\{rawUnit\}\)`\)/, 'the raw suffix is swapped, not appended');
  assert.match(table, /formatUnit\(rawUnit\)/, 'the replacement is the formatted unit');
  assert.doesNotMatch(table, /\{table\.time_header\} \(\{|table\.value_header\} \(\{|timeUnit\}\)|valueUnit\}\)/, 'no appended duplicate unit');
});

test('verdict tab binds case and unit selects, thresholds show units', async () => {
  const [panel, fields] = await Promise.all([
    read('../src/FindingsPanel.tsx'),
    read('../src/FindingsCriterionFields.tsx'),
  ]);
  assert.match(panel, /<select[^>]*genkey|caseOptions|workspaceCases/i, 'case comes from a workspace select');
  assert.doesNotMatch(panel, /placeholder=\{t\('findings\.genkeyPlaceholder'\)\}/, 'no typed filename');
  assert.match(fields, /<select[^>]*unit|unitOptions|unitChoices/i, 'unit comes from a select');
  assert.match(fields, /\(.*unit.*\)|unit.*suffix/i, 'threshold labels show their unit');
});
