import { useRef, useState } from 'react';
import type { I18nKey } from './i18n/ko.ts';
import * as session from './session';
import { createRequestEpoch } from './requestEpoch';
import { errorCodeOf } from './sessionResponse';
import { overlayRefusal } from './crossRunOverlay.mjs';
import { pickAutoPlotVariable } from './trendGeometry';
import {
  acceptSeriesUnitPreferences,
  discoveryMatchesPreferredView,
  loadUnitPreferences,
  preferredSeriesView,
  saveUnitPreferences,
} from './unitPreferences';

const OVERLAY_COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)', 'var(--s5)'] as const;
const MAX_OVERLAYS = OVERLAY_COLORS.length;

export type PlottedSeries = {
  readonly key: string;
  readonly variable: session.ResultVar;
  readonly series: session.Series;
  readonly view: session.SeriesViewSpec;
  readonly color: string;
  /** The result file this series is read from. */
  readonly fileId: string;
  /** The other run's file name when the series comes from another run; null for this file. */
  readonly source: string | null;
};

export function resultVariableKey(variable: session.ResultVar): string {
  return `${variable.variable}\u0000${variable.position}`;
}

function lastSeries(items: readonly PlottedSeries[]): PlottedSeries | null {
  return items[items.length - 1] ?? null;
}

export type OverlayText = (key: I18nKey, vars?: Record<string, string | number>) => string;

export function useResultSeriesOverlay(
  selected: session.ResultFile | null,
  t: OverlayText | null = null,
) {
  const [plottedSeries, setPlottedSeries] = useState<readonly PlottedSeries[]>([]);
  const [activeSeriesKey, setActiveSeriesKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<{ readonly text: string; readonly code: string | null }>({ text: '', code: null });
  const setError = (text: string, code: string | null = null) => setFailure({ text, code });
  const requestRef = useRef(createRequestEpoch());
  const preferencesRef = useRef(loadUnitPreferences());
  const active = plottedSeries.find((item) => item.key === activeSeriesKey) ?? lastSeries(plottedSeries);

  const autoPlottedRef = useRef<string | null>(null);

  function reset(): void {
    requestRef.current.invalidate();
    setPlottedSeries([]);
    setActiveSeriesKey(null);
    setLoading(false);
    setError('');
    autoPlottedRef.current = null;
  }

  /** Plot the first pressure variable (else the first) once per new variable list. */
  function ensureAutoPlot(variables: readonly session.ResultVar[]): void {
    const scope = selected?.id ?? '';
    if (scope === '' || autoPlottedRef.current === scope || plottedSeries.length > 0) return;
    const choice = pickAutoPlotVariable(variables);
    if (!choice) return;
    autoPlottedRef.current = scope;
    void toggleVariable(choice);
  }

  function persistPreferences(viewed: session.Series): void {
    const next = acceptSeriesUnitPreferences(
      preferencesRef.current,
      viewed.view.value_conversion,
      viewed.view.time_conversion,
    );
    if (next === preferencesRef.current) return;
    preferencesRef.current = next;
    saveUnitPreferences(undefined, next);
  }

  function removeSeries(key: string): void {
    requestRef.current.invalidate();
    const remaining = plottedSeries.filter((item) => item.key !== key);
    setPlottedSeries(remaining);
    if (activeSeriesKey === key) setActiveSeriesKey(lastSeries(remaining)?.key ?? null);
    setError('');
    setLoading(false);
  }

  async function toggleVariable(variable: session.ResultVar): Promise<void> {
    if (!selected || selected.suffix === '.ppl') return;
    const key = resultVariableKey(variable);
    if (plottedSeries.some((item) => item.key === key)) {
      removeSeries(key);
      return;
    }
    if (plottedSeries.length >= MAX_OVERLAYS) {
      setError(t?.('results.overlayLimit', { max: MAX_OVERLAYS }) ?? `Overlay limit reached. Remove one of the ${MAX_OVERLAYS} plotted series first.`);
      return;
    }

    const requestId = requestRef.current.begin();
    setError('');
    setLoading(true);
    try {
      const discovered = await session.fetchSeries(selected.id, variable.variable, variable.position);
      if (!requestRef.current.isCurrent(requestId)) return;
      const sameDimension = active?.series.view.value_conversion.dimension != null
        && active.series.view.value_conversion.dimension === discovered.view.value_conversion.dimension;
      const nextView: session.SeriesViewSpec = active ? {
        ...(sameDimension && active.view.value_unit ? { value_unit: active.view.value_unit } : {}),
        ...(active.view.time_unit ? { time_unit: active.view.time_unit } : {}),
        quantity_kind: discovered.view.value_conversion.quantity_kind,
        range: active.view.range,
      } : preferredSeriesView(
        preferencesRef.current,
        discovered.view.value_conversion,
        discovered.view.time_conversion,
      );
      const viewed = discoveryMatchesPreferredView(discovered, nextView)
        ? discovered
        : await session.fetchSeries(selected.id, variable.variable, variable.position, nextView);
      if (!requestRef.current.isCurrent(requestId)) return;
      persistPreferences(viewed);
      const usedColors = new Set(plottedSeries.map((item) => item.color));
      const color = OVERLAY_COLORS.find((candidate) => !usedColors.has(candidate)) ?? OVERLAY_COLORS[0];
      setPlottedSeries((current) => [...current, { key, variable, series: viewed, view: nextView, color, fileId: selected.id, source: null }]);
      setActiveSeriesKey(key);
    } catch (cause) {
      if (requestRef.current.isCurrent(requestId)) {
        setError(cause instanceof Error ? cause.message : String(cause), errorCodeOf(cause));
      }
    } finally {
      if (requestRef.current.isCurrent(requestId)) setLoading(false);
    }
  }

  /** The active variable from another run's file, only when its unit and time base match. */
  async function addFromRun(file: session.ResultFile, label: string = file.name): Promise<void> {
    if (!selected || !active || file.id === selected.id || file.suffix !== selected.suffix) return;
    const key = `${file.id}\u0001${resultVariableKey(active.variable)}`;
    if (plottedSeries.some((item) => item.key === key)) return;
    if (plottedSeries.length >= MAX_OVERLAYS) {
      setError(t?.('results.overlayLimit', { max: MAX_OVERLAYS }) ?? `Overlay limit reached. Remove one of the ${MAX_OVERLAYS} plotted series first.`);
      return;
    }
    const requestId = requestRef.current.begin();
    setError('');
    setLoading(true);
    try {
      const viewed = await session.fetchSeries(file.id, active.variable.variable, active.variable.position, active.view);
      if (!requestRef.current.isCurrent(requestId)) return;
      const refusal = overlayRefusal(active.series, viewed);
      if (refusal) {
        setError(t?.(refusal.key, { ...refusal.params, name: label }) ?? refusal.key);
        return;
      }
      const usedColors = new Set(plottedSeries.map((item) => item.color));
      const color = OVERLAY_COLORS.find((candidate) => !usedColors.has(candidate)) ?? OVERLAY_COLORS[0];
      setPlottedSeries((current) => [...current, { key, variable: active.variable, series: viewed, view: active.view, color, fileId: file.id, source: label }]);
    } catch (cause) {
      // Most often the other run has no such variable; say so in the UI language.
      if (requestRef.current.isCurrent(requestId)) {
        setError(t?.('overlay.refuse.unreadable', { variable: active.variable.variable, name: label }) ?? (cause instanceof Error ? cause.message : String(cause)));
      }
    } finally {
      if (requestRef.current.isCurrent(requestId)) setLoading(false);
    }
  }

  async function changeView(nextView: session.SeriesViewSpec): Promise<void> {
    if (!selected || plottedSeries.length === 0) return;
    const requestId = requestRef.current.begin();
    setError('');
    setLoading(true);
    try {
      const activeDimension = active?.series.view.value_conversion.dimension ?? null;
      const viewed = await Promise.all(plottedSeries.map(async (item) => {
        const sameDimension = activeDimension != null && activeDimension === item.series.view.value_conversion.dimension;
        const itemView: session.SeriesViewSpec = {
          ...(sameDimension && nextView.value_unit ? { value_unit: nextView.value_unit } : {}),
          ...(nextView.time_unit ? { time_unit: nextView.time_unit } : {}),
          quantity_kind: item.series.view.value_conversion.quantity_kind,
          range: nextView.range,
        };
        const nextSeries = await session.fetchSeries(item.fileId, item.variable.variable, item.variable.position, itemView);
        return {
          ...item,
          view: itemView,
          series: nextSeries,
        };
      }));
      if (!requestRef.current.isCurrent(requestId)) return;
      const activeViewed = viewed.find((item) => item.key === activeSeriesKey) ?? viewed[0];
      if (activeViewed) persistPreferences(activeViewed.series);
      setPlottedSeries(viewed);
    } catch (cause) {
      if (requestRef.current.isCurrent(requestId)) {
        setError(cause instanceof Error ? cause.message : String(cause), errorCodeOf(cause));
      }
    } finally {
      if (requestRef.current.isCurrent(requestId)) setLoading(false);
    }
  }

  return {
    plottedSeries,
    activeSeriesKey,
    activeVariable: active?.variable ?? null,
    activeSeries: active?.series ?? null,
    viewSpec: active?.view ?? null,
    /** The file the active series is read from: another run's file for a cross-run series. */
    activeFileId: active?.fileId ?? null,
    loading,
    error: failure.text,
    /** The server's stable code for the error above, or null (a message the app wrote, or an uncoded refusal). */
    errorCode: failure.code,
    reset,
    toggleVariable,
    removeSeries,
    addFromRun,
    ensureAutoPlot,
    changeView,
    activateSeries: setActiveSeriesKey,
  };
}
