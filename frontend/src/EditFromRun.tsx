import { useLocale } from './i18n/index.ts';
import { editFromRun, type EditSource } from './editFromRunModel.mjs';
import { requestEditFromRun } from './shell/workspaceEvents';
import { Button } from './ui/Button';

/** Opens the edit table on the case this run used, with nothing typed in; or says why it cannot. */
export default function EditFromRun({ result }: { readonly result: { readonly edit_source?: EditSource } }) {
  const { t } = useLocale();
  const offer = editFromRun(result);
  if (!offer) return null;
  if (offer.kind === 'reason') return <span className="result-edit-reason">{t(offer.key)}</span>;
  return (
    <Button variant="secondary" onClick={() => window.dispatchEvent(requestEditFromRun(offer.rel))}>
      {t('results.editFromRun')}
    </Button>
  );
}
