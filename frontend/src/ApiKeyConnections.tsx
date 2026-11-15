import { useEffect, useState } from 'react';
import {
  deleteApiKeyConnection,
  fetchApiKeyConnections,
  saveApiKeyConnection,
  verifyApiKeyConnection,
  type ApiKeyConnection,
  type ApiKeyProtocol,
} from './apiKeyApi';
import { outcomeSentence } from './apiKeyOutcomes';
import { useLocale, type I18nKey } from './i18n/index.ts';
import { Button } from './ui/Button';
import { Field } from './ui/Field';
import { Select } from './ui/Select';

const PROTOCOLS: readonly ApiKeyProtocol[] = ['openai-responses', 'openai-chat'];

export default function ApiKeyConnections({ onChanged }: { readonly onChanged: () => void }) {
  const [connections, setConnections] = useState<readonly ApiKeyConnection[]>([]);
  const [label, setLabel] = useState('');
  const [protocol, setProtocol] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [noticeOutcome, setNoticeOutcome] = useState<string | null>(null);
  const [noticeKey, setNoticeKey] = useState<I18nKey | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const { locale, t } = useLocale();

  async function refresh() {
    try {
      setConnections(await fetchApiKeyConnections());
    } catch {
      setLoadFailed(true);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  function clearNotice() {
    setNoticeOutcome(null);
    setNoticeKey(null);
  }

  async function save() {
    if (busy || !label.trim() || !protocol || !baseUrl.trim() || !model.trim() || !key) return;
    setBusy(true);
    clearNotice();
    try {
      const saved = await saveApiKeyConnection({
        label: label.trim(),
        protocol: protocol as ApiKeyProtocol,
        base_url: baseUrl.trim(),
        model: model.trim(),
        key,
      });
      setKey('');
      setNoticeOutcome(saved.outcome);
      await refresh();
      onChanged();
    } catch {
      setNoticeKey('apikey.saveFailed');
    } finally {
      setBusy(false);
    }
  }

  async function verify(id: string) {
    setVerifyingId(id);
    clearNotice();
    try {
      const result = await verifyApiKeyConnection(id);
      setNoticeOutcome(result.outcome);
      await refresh();
      onChanged();
    } catch {
      setNoticeKey('apikey.verifyFailed');
    } finally {
      setVerifyingId(null);
    }
  }

  async function remove(id: string) {
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id);
      return;
    }
    setConfirmDeleteId(null);
    try {
      await deleteApiKeyConnection(id);
      await refresh();
      onChanged();
    } catch {
      setNoticeKey('apikey.deleteFailed');
    }
  }

  const notice = noticeOutcome ? outcomeSentence(noticeOutcome, locale) : noticeKey ? t(noticeKey) : '';

  return (
    <div className="apikey-connections" aria-label={t('apikey.label')}>
      {loadFailed && <p className="apikey-error" role="alert">{t('apikey.listFailed')}</p>}
      {connections.length > 0 && (
        <ul className="apikey-list">
          {connections.map((connection) => (
            <li key={connection.id} className="apikey-row">
              <div className="apikey-meta">
                <strong>{connection.label}</strong>
                <span>{connection.protocol} · {connection.base_url} · {connection.model}</span>
                {connection.has_key && <span>{t('apikey.savedMeta', { last4: connection.last4 })}</span>}
                {connection.verified && <span className="apikey-verified">{t('apikey.verified')}</span>}
              </div>
              <div className="apikey-actions">
                <Button variant="secondary" onClick={() => { void verify(connection.id); }} disabled={verifyingId !== null} busy={verifyingId === connection.id} busyLabel={t('apikey.verifying')}>{t('apikey.verifyAction')}</Button>
                <Button
                  variant="secondary"
                  onClick={() => { void remove(connection.id); }}
                >
                  {confirmDeleteId === connection.id ? t('apikey.deleteConfirm') : t('apikey.deleteAction')}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <div className="apikey-form">
        <Field label={t('apikey.nameLabel')} controlId="apikey-name">
          <input value={label} maxLength={40} onChange={(event) => setLabel(event.target.value)} placeholder={t('apikey.namePlaceholder')} />
        </Field>
        <Field label={t('apikey.protocolLabel')} controlId="apikey-protocol">
          <Select
            ariaLabel={t('apikey.protocolLabel')}
            value={protocol}
            onChange={setProtocol}
            options={[{ value: '', label: t('apikey.protocolPlaceholder') }, ...PROTOCOLS.map((name) => ({ value: name, label: name }))]}
          />
        </Field>
        <Field label={t('apikey.baseUrlLabel')} controlId="apikey-base-url">
          <input inputMode="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" />
        </Field>
        <Field label={t('apikey.modelLabel')} controlId="apikey-model">
          <input value={model} onChange={(event) => setModel(event.target.value)} placeholder={t('apikey.modelPlaceholder')} />
        </Field>
        <Field label={t('apikey.keyLabel')} controlId="apikey-key">
          <input type="password" autoComplete="off" spellCheck={false} value={key} onChange={(event) => setKey(event.target.value)} />
        </Field>
        <div className="apikey-actions">
          <Button variant="primary" onClick={() => { void save(); }} disabled={busy} busy={busy} busyLabel={t('apikey.saving')}>{t('apikey.save')}</Button>
        </div>
      </div>
      {notice && <p className="apikey-notice" role="status">{notice}</p>}
    </div>
  );
}
