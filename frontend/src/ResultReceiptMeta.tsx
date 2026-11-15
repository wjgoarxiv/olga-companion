import type { ResultFile } from './session';
import { useLocale } from './i18n/index.ts';
import { modifiedLabel, resultStatusKey } from './resultPresentation';

export default function ResultReceiptMeta({ result }: { readonly result: ResultFile }) {
  const { t, locale } = useLocale();
  return (
    <>
      {result.run_id && <span><strong>{t('results.metaRun')}</strong>{result.run_id}</span>}
      <span><strong>{t('results.metaStatus')}</strong>{t(resultStatusKey(result))}</span>
      <span><strong>{t('results.metaModified')}</strong>{modifiedLabel(result.modified_ns, locale)}</span>
      <span><strong>{t('results.metaOrigin')}</strong>{t('results.metaReceiptBacked')}</span>
      {(result.runtime_version || result.lineage?.runtime_version) && <span><strong>{t('results.metaRuntime')}</strong>OLGA {result.runtime_version || result.lineage?.runtime_version}{result.runtime_kind || result.lineage?.runtime_kind ? ` · ${result.runtime_kind || result.lineage?.runtime_kind}` : ''}</span>}
      {(result.source_name || result.lineage?.source_name) && <span><strong>{t('results.metaSource')}</strong>{result.source_name || result.lineage?.source_name}</span>}
      {result.output_sha256 && <span><strong>{t('results.metaDigest')}</strong>{result.output_sha256.slice(0, 12)}…</span>}
    </>
  );
}
