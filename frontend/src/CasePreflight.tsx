import { useEffect, useId, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { ko } from './i18n/ko.ts';
import { orderedItems, rowOpener, type PreflightItem } from './casePreflightModel.mjs';
import { displayFromText } from './displayQuantity.mjs';
import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';

type Translate = (key: string, vars?: Record<string, string | number>) => string;
type OpenRow = (rel: string, rowId: string) => void;

const known = (key: string): boolean => key in ko;

/** The sentence for one item from copy the app already has; null when no sentence exists yet. */
function itemText(item: PreflightItem, t: Translate): string | null {
  const values = item.values ?? {};
  if (item.message_code === 'value_unset') {
    // The field label may already end in its keyword "(MAXDT)"; the sentence names the keyword once.
    const field = item.field ? t(`caseEdit.field.${item.field}`).replace(/\s*\([^)]*\)\s*$/, '') : '';
    return t('preflight.code.value_unset', { field, target: item.target ?? '' });
  }
  const range = `run.sweepRange.${values.status}.${values.relation}`;
  if (item.message_code.startsWith('pvt_') && known(range)) {
    return t(range, { ...values, value: displayFromText(values.value), quantity: t(`run.sweepRange.quantity.${values.quantity}`) });
  }
  if (known(`lint.${item.message_code}`)) return t(`lint.${item.message_code}`, values);
  const key = `preflight.code.${item.message_code}`;
  return known(key) ? t(key, { target: item.target ?? '' }) : null;
}

type PanelProps = {
  readonly items: readonly PreflightItem[] | null;
  readonly failed?: boolean;
  readonly rel: string;
  readonly onOpenRow: OpenRow;
};

/** The labelled checklist: nothing is filled in, and an item that names a row opens that row. */
export function CasePreflightPanel({ items, failed = false, rel, onOpenRow }: PanelProps) {
  const { t } = useLocale();
  return (
    <section className="case-preflight" aria-label={t('preflight.title')} aria-busy={items === null && !failed}>
      <h4 className="case-preflight-title">{t('preflight.title')}</h4>
      {failed ? <p role="status">{t('preflight.failed')}</p>
        : items === null ? <p role="status">{t('preflight.loading')}</p>
          : <CasePreflightList items={items} rel={rel} onOpenRow={onOpenRow} />}
    </section>
  );
}

function CasePreflightList({ items, rel, onOpenRow }: { readonly items: readonly PreflightItem[]; readonly rel: string; readonly onOpenRow: OpenRow }) {
  const { t } = useLocale();
  const listId = useId();
  return (
    <ul className="case-preflight-list">
      {orderedItems(items).map((item, index) => {
        const text = itemText(item, t);
        const open = rowOpener(rel, item, onOpenRow);
        const state = item.state === 'ok' || item.state === 'missing' ? item.state : 'warn';
        const textId = `${listId}-${index}`;
        return (
          <li key={`${item.id}-${index}`} className={`case-preflight-item is-${state}`}>
            <span className="case-preflight-state">{t(`preflight.state.${state}`)}</span>
            <span className="case-preflight-text" id={textId}>
              {text ?? <>{t('serverError.untranslated')} <code>{item.message_code}</code></>}
            </span>
            {item.detail && <pre className="error-detail-raw" lang="en">{item.detail}</pre>}
            {open && <button type="button" className="case-preflight-open" aria-describedby={textId} onClick={open}>{t('preflight.openRow')}</button>}
          </li>
        );
      })}
    </ul>
  );
}

/** The pre-run file check for the selected case. It reads the file and starts nothing. */
export default function CasePreflight({ rel, onOpenRow }: { readonly rel: string; readonly onOpenRow: OpenRow }) {
  const [items, setItems] = useState<readonly PreflightItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setFailed(false);
    apiFetch('/api/case-preflight?rel=' + encodeURIComponent(rel))
      .then(jsonOrThrow)
      .then((body) => { if (!cancelled) setItems((body as { items?: PreflightItem[] }).items ?? []); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [rel]);
  return <CasePreflightPanel items={items} failed={failed} rel={rel} onOpenRow={onOpenRow} />;
}
