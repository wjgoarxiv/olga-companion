import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  EXAMPLES_OPEN_EVENT,
  claimExampleInstall,
  exampleErrorKey,
  fetchExamples,
  getExampleInstallBusy,
  installExample,
  releaseExampleInstall,
  subscribeExampleInstallBusy,
  type ExampleCard,
  type ExampleInstall,
} from './examplesApi';
import { useLocale } from './i18n/index.ts';
import type { I18nKey } from './i18n/ko.ts';
import { Button } from './ui/Button';
import './styles/example-gallery.css';

function cardTitle(item: ExampleCard, locale: string): string {
  return locale === 'en' ? item.title_en : item.title_ko;
}

function cardBody(item: ExampleCard, locale: string): string {
  return locale === 'en' ? item.description_en : item.description_ko;
}

export function ExampleGallery({ disabled = false }: { readonly disabled?: boolean }) {
  const { t, locale } = useLocale();
  const [items, setItems] = useState<readonly ExampleCard[]>([]);
  const busyId = useSyncExternalStore(subscribeExampleInstallBusy, getExampleInstallBusy, getExampleInstallBusy);
  const [notice, setNotice] = useState('');
  const [errorKey, setErrorKey] = useState<I18nKey | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchExamples()
      .then((next) => { if (!cancelled) setItems(next); })
      .catch(() => { if (!cancelled) setErrorKey('examples.loadFailed'); })
      .finally(() => { if (!cancelled) setLoaded(true); });
    return () => { cancelled = true; };
  }, []);

  async function start(item: ExampleCard) {
    if (!claimExampleInstall(item.id)) return;
    setErrorKey(null);
    setNotice('');
    try {
      const installed: ExampleInstall = await installExample(item.id);
      setNotice(t('examples.nextValidate', { name: installed.case_name }));
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '';
      setErrorKey(exampleErrorKey(message));
    } finally {
      releaseExampleInstall(item.id);
    }
  }

  return (
    <section className="example-gallery" data-tour="demo-case" aria-label={t('examples.title')}>
      <h3>{t('examples.title')}</h3>
      <p className="example-lede">{t('examples.lede')}</p>
      {!loaded && <p role="status">{t('examples.loading')}</p>}
      {loaded && items.length === 0 && errorKey === null && <p>{t('examples.empty')}</p>}
      <ul className="example-list">
        {items.map((item) => {
          const topology = t(`examples.topology.${item.topology}`);
          const fluid = t(`examples.fluid.${item.fluid}`);
          return (
            <li key={item.id} className="example-card">
              <strong>{cardTitle(item, locale)}</strong>
              <p>{cardBody(item, locale)}</p>
              <p className="example-meta">{topology} · {fluid}</p>
              <Button
                variant="primary"
                disabled={disabled || busyId !== null}
                busy={busyId === item.id}
                busyLabel={t('examples.installing')}
                onClick={() => { void start(item); }}
              >
                {t('examples.start')}
              </Button>
            </li>
          );
        })}
      </ul>
      {notice && <p className="example-next">{notice}</p>}
      {errorKey !== null && <p className="example-error" role="alert">{t(errorKey)}</p>}
    </section>
  );
}

export function ExampleGalleryDialog() {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener(EXAMPLES_OPEN_EVENT, onOpen);
    return () => window.removeEventListener(EXAMPLES_OPEN_EVENT, onOpen);
  }, []);

  useEffect(() => {
    if (!open) return;
    dialogRef.current?.focus();
  }, [open]);

  if (!open) return null;
  return (
    <div className="example-gallery-layer" onMouseDown={(event) => {
      if (event.target === event.currentTarget) setOpen(false);
    }}>
      <div
        ref={dialogRef}
        className="example-gallery-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('examples.title')}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key !== 'Escape') return;
          event.stopPropagation();
          setOpen(false);
        }}
      >
        <ExampleGallery />
        <div className="example-gallery-close">
          <Button variant="secondary" onClick={() => setOpen(false)}>{t('shell.close')}</Button>
        </div>
      </div>
    </div>
  );
}
