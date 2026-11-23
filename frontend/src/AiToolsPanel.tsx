/* Settings "Connect AI tools" (0.1.20 row 15). Codex and Gemini CLI get the app's MCP entry
   written into their config file (after a backup; only that entry). Claude Code's docs ask
   not to edit its file, so it gets the command to paste. Anything an outside tool asks to
   write or run still waits for an approval card in this app. */
import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react';
import { apiFetch } from './sessionTransport';
import { jsonOrThrow } from './sessionResponse';
import { useLocale } from './i18n/index.ts';

export type AiTool = {
  readonly product: string;
  readonly label: string;
  readonly mode: 'file' | 'command';
  readonly path: string | null;
  readonly connected: boolean;
};

export type AiToolOutcome =
  | { readonly kind: 'command'; readonly command: string; readonly removeCommand?: string | null }
  | { readonly kind: 'removeCommand'; readonly command: string }
  | { readonly kind: 'done'; readonly backup?: string | null }
  | { readonly kind: 'error'; readonly detail?: string | null }
  | null;

export function AiToolRow({ tool, outcome, busy, onConnect, onRemove }: {
  readonly tool: AiTool;
  readonly outcome: AiToolOutcome;
  readonly busy: boolean;
  readonly onConnect: () => void;
  readonly onRemove: () => void;
}): ReactElement {
  const { t } = useLocale();
  const id = `ai-tool-${tool.product}`;
  const commandRef = useRef<HTMLTextAreaElement | null>(null);
  const shownCommand = outcome?.kind === 'command' || outcome?.kind === 'removeCommand' ? outcome.command : null;
  // A new command moves focus to it, so a keyboard user lands where the next step is.
  useEffect(() => { if (shownCommand) commandRef.current?.focus(); }, [shownCommand]);
  // Busy buttons stay focusable (aria-disabled), so focus is not lost while a change runs.
  const guard = (action: () => void) => () => { if (!busy) action(); };
  const state = !tool.connected
    ? t('aiTools.notConnected')
    : tool.mode === 'command' ? t('aiTools.commandIssued') : t('aiTools.connected');
  return (
    <li className="ai-tool-row" aria-labelledby={`${id}-name`}>
      <div className="ai-tool-head">
        <strong id={`${id}-name`}>{tool.label}</strong>
        <span className={tool.connected ? 'ai-tool-state is-on' : 'ai-tool-state'}>
          {state}
        </span>
      </div>
      <p className="settings-note">
        {tool.mode === 'file' && tool.path
          ? t('aiTools.fileNote', { path: tool.path })
          : t('aiTools.commandNote')}
      </p>
      <div className="ai-tool-actions">
        <button type="button" onClick={guard(onConnect)} aria-disabled={busy || undefined}>
          {tool.connected ? t('aiTools.reconnect') : t('aiTools.connect')}
        </button>
        {tool.connected && (
          <button type="button" onClick={guard(onRemove)} aria-disabled={busy || undefined}>{t('aiTools.remove')}</button>
        )}
      </div>
      {outcome?.kind === 'command' && (
        <div className="ai-tool-command">
          <textarea
            ref={commandRef}
            readOnly
            rows={3}
            aria-label={t('aiTools.commandLabel', { name: tool.label })}
            value={outcome.command}
            onFocus={(event) => event.currentTarget.select()}
          />
          <small>{t('aiTools.commandHint')}</small>
          {outcome.removeCommand && (
            <textarea
              readOnly
              rows={1}
              aria-label={t('aiTools.removeFirstLabel', { name: tool.label })}
              value={outcome.removeCommand}
              onFocus={(event) => event.currentTarget.select()}
            />
          )}
        </div>
      )}
      {outcome?.kind === 'removeCommand' && (
        <div className="ai-tool-command">
          <textarea
            ref={commandRef}
            readOnly
            rows={1}
            aria-label={t('aiTools.removeLabel', { name: tool.label })}
            value={outcome.command}
            onFocus={(event) => event.currentTarget.select()}
          />
          <small>{t('aiTools.removeHint')}</small>
        </div>
      )}
      <p className="ai-tool-done" role="status">
        {outcome?.kind === 'done' ? (outcome.backup ? t('aiTools.doneBackup', { backup: outcome.backup }) : t('aiTools.done')) : null}
      </p>
      {outcome?.kind === 'error' && (
        <p className="ai-tool-error" role="alert">
          {t('aiTools.failed')}
          {outcome.detail && <small className="ai-tool-detail">{outcome.detail}</small>}
        </p>
      )}
    </li>
  );
}

export default function AiToolsPanel(): ReactElement {
  const { t } = useLocale();
  const [tools, setTools] = useState<readonly AiTool[]>([]);
  const [outcomes, setOutcomes] = useState<Record<string, AiToolOutcome>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const payload = (await jsonOrThrow(await apiFetch('/api/ai-tools'))) as { tools?: AiTool[] };
      setTools(payload.tools ?? []);
      setLoadFailed(false);
    } catch {
      setTools([]);
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const change = useCallback(async (product: string, action: 'connect' | 'remove') => {
    setBusy(product);
    try {
      const response = await apiFetch(`/api/ai-tools/${product}/${action}`, { method: 'POST' });
      const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
      if (!response.ok) {
        const detail = typeof payload.detail === 'string' ? payload.detail : null;
        setOutcomes((current) => ({ ...current, [product]: { kind: 'error', detail } }));
        return;
      }
      const command = typeof payload.command === 'string' ? payload.command : null;
      const outcome: AiToolOutcome = command === null
        ? { kind: 'done', backup: typeof payload.backup === 'string' ? payload.backup : null }
        : action === 'remove'
          ? { kind: 'removeCommand', command }
          : { kind: 'command', command, removeCommand: typeof payload.remove_command === 'string' ? payload.remove_command : null };
      setOutcomes((current) => ({ ...current, [product]: outcome }));
      await load();
    } catch {
      setOutcomes((current) => ({ ...current, [product]: { kind: 'error', detail: null } }));
    } finally {
      setBusy(null);
    }
  }, [load]);

  return (
    <article className="settings-card ai-tools-card">
      <h3 className="settings-h">{t('aiTools.title')}</h3>
      <p className="settings-note">{t('aiTools.lede')}</p>
      {loadFailed && <p className="ai-tool-error" role="alert">{t('aiTools.loadFailed')}</p>}
      <ul className="ai-tool-list">
        {tools.map((tool) => (
          <AiToolRow
            key={tool.product}
            tool={tool}
            outcome={outcomes[tool.product] ?? null}
            busy={busy !== null}
            onConnect={() => void change(tool.product, 'connect')}
            onRemove={() => void change(tool.product, 'remove')}
          />
        ))}
      </ul>
    </article>
  );
}
