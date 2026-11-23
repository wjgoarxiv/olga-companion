import { changeLabel } from './runIdentity.mjs';

// How another run is named in the picker and on its chip: the change that was approved for its
// case when there is one, then the case it ran and when, because every run's result file has the
// same name (case.tpl).

/** "<case or file name> · <date and time>" in the UI locale; the name alone when the time is unknown. */
function caseAndTime(file, locale) {
  const name = file.source_name || file.name;
  const when = new Date(Number(file.modified_ns) / 1_000_000);
  if (Number.isNaN(when.getTime())) return name;
  return `${name} · ${when.toLocaleString(locale === 'en' ? 'en-US' : 'ko-KR', { dateStyle: 'medium', timeStyle: 'short' })}`;
}

/** The approved change first ("PC PID 설정값 20→25 bar — case · time"); a hand-made case keeps "case · time". */
export function runLabel(file, locale, t) {
  const change = t ? changeLabel(file, t) : null;
  const base = caseAndTime(file, locale);
  return change ? `${change} — ${base}` : base;
}

/** A chip's source line in the current UI language: another run is renamed after a language switch. */
export function chipSource(series, runs, locale, t) {
  const run = series.source ? runs.find((file) => file.id === series.fileId) : undefined;
  return run ? runLabel(run, locale, t) : series.source;
}
