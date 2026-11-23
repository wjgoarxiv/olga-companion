import { useLocale } from './i18n/index.ts';
import { ko } from './i18n/ko.ts';

/** The headline key for a server error code; null when the app has no sentence for it yet. */
export function errorHeadlineKey(code: string): string | null {
  const key = `serverError.${code}`;
  return key in ko ? key : null;
}

/** A server refusal: a headline in the app language for a known code, and the server's own words kept
 *  below in a selectable block, never translated. An unknown code says it is not translated yet. */
export default function ErrorDetail({ code, text }: { readonly code: string; readonly text: string }) {
  const { t } = useLocale();
  const key = errorHeadlineKey(code);
  return (
    <span className="error-detail">
      <span className="error-detail-headline">{key ? t(key) : t('serverError.untranslated')}</span>
      <pre className="error-detail-raw" lang="en">{text.trim() || t('serverError.noText')}</pre>
    </span>
  );
}
