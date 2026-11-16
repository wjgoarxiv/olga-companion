import BrandMark from '../BrandMark';
import WorkspaceBar from '../WorkspaceBar';
import type { NativeSelectedContext } from '../session';
import type { WorkspaceCase } from '../session';
import { useRef } from 'react';
import { IconButton } from '../ui/IconButton';
import { Icon } from '../ui/Icon';
import { motionAllowsFull, applyThemeChoice, useAppearance } from '../appearance';
import { parseLocale, useLocale, type Locale } from '../i18n/index.ts';
import { useRunConsoleSnapshot } from '../runConsole';
import { caseActionsEnabled } from './useWorkbenchCommands';
import { useTutorialBadge } from '../TutorialHost';
import { requestTutorialOpen } from '../tutorialTour.mjs';

export function themeRevealAt(x: number, y: number): void {
  const root = document.documentElement;
  const next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  const apply = () => {
    applyThemeChoice(next);
  };
  const doc = document as Document & {
    startViewTransition?: (callback: () => void) => { finished: Promise<void> };
  };
  if (motionAllowsFull() && typeof doc.startViewTransition === 'function') {
    const clear = () => {
      root.style.removeProperty('--vt-x');
      root.style.removeProperty('--vt-y');
      root.style.removeProperty('--vt-old-anim');
      root.style.removeProperty('--vt-new-anim');
    };
    root.style.setProperty('--vt-x', `${x}px`);
    root.style.setProperty('--vt-y', `${y}px`);
    root.style.setProperty('--vt-old-anim', 'vt-out 160ms var(--ease-exit)');
    root.style.setProperty('--vt-new-anim', 'vt-reveal 420ms var(--ease-enter)');
    doc.startViewTransition(apply).finished.then(clear, clear);
    return;
  }
  apply();
}

export default function TitleBar({
  activeCaseName,
  cases,
  workspaceRoot,
  contextGeneration,
  onPick,
  onContextSelected,
  onHome,
  onValidate,
  onPreviewRun,
  onOpenRun,
  onOpenPalette,
}: {
  readonly activeCaseName: string | null;
  readonly cases: WorkspaceCase[];
  readonly workspaceRoot: string;
  readonly contextGeneration: number;
  readonly onPick: (rel: string) => void;
  readonly onContextSelected: (context: NativeSelectedContext) => void | Promise<void>;
  readonly onHome: () => void;
  readonly onValidate: () => void;
  readonly onPreviewRun: () => void;
  readonly onOpenRun: () => void;
  readonly onOpenPalette: () => void;
}) {
  const { t, locale, setLocale } = useLocale();
  const { resolvedTheme } = useAppearance();
  const themeButtonRef = useRef<HTMLButtonElement | null>(null);
  // The Run button shows a progress fill while a preview or run is in flight.
  const runBusy = useRunConsoleSnapshot().starting;
  // M6 gating: case actions need an active case. The derivation lives in
  // useWorkbenchCommands (shared with W3-L3); the described reason gives
  // assistive tech the why. Paint stays the dashed-disabled Button pattern.
  const canValidate = caseActionsEnabled(activeCaseName);
  const canPreview = caseActionsEnabled(activeCaseName);
  const canRun = caseActionsEnabled(activeCaseName);
  const tutorialDone = useTutorialBadge();

  function switchLanguage(): void {
    const next: Locale = locale === 'ko' ? 'en' : 'ko';
    if (parseLocale(next) !== null) setLocale(next);
  }

  return (
    <header className="wb-titlebar">
      <button type="button" className="wordmark" aria-label={t('app.homeAria')} onClick={onHome}>
        <BrandMark className="wordmark-mark" />
        <span className="wordmark-primary" aria-hidden="true">OLGA</span>
        <span className="wordmark-secondary" aria-hidden="true">COMPANION</span>
      </button>
      <nav className="wb-crumb" aria-label={t('status.caseContext')}>
        <WorkspaceBar
          activeName={activeCaseName}
          cases={cases}
          root={workspaceRoot}
          contextGeneration={contextGeneration}
          onPick={onPick}
          onContextSelected={onContextSelected}
        />
      </nav>
      <span className="wb-spacer" aria-hidden="true" />
      <i className="wb-barcode" aria-hidden="true" />
      <div className="wb-title-actions" role="group" aria-label={t('shell.titleActions')}>
        <button type="button" className="wb-btn" data-tour="validate" onClick={onValidate} disabled={!canValidate} aria-describedby={!canValidate ? 'titlebar-needcase-hint' : undefined}><Icon name="validate" size={16} />{t('shell.validate')}</button>
        <button type="button" className="wb-btn" onClick={onPreviewRun} disabled={!canPreview} aria-describedby={!canPreview ? 'titlebar-needcase-hint' : undefined}><Icon name="file" size={16} />{t('shell.previewRun')}</button>
        <button type="button" className="wb-btn wb-btn-primary" data-tour="run" data-busy={runBusy || undefined} onClick={onOpenRun} disabled={!canRun} aria-describedby={!canRun ? 'titlebar-needcase-hint' : undefined}><Icon name="run" size={16} />{t('shell.run')}</button>
        <button type="button" className="wb-btn tutorial-btn" onClick={requestTutorialOpen} aria-label={t('tutorial.button')}>{t('tutorial.button')}{tutorialDone ? null : <i className="tutorial-dot" aria-hidden="true" />}</button>
        {!canValidate && <span id="titlebar-needcase-hint" className="ui-visually-hidden">{t('titlebar.needCase')}</span>}
        <IconButton label={t('shell.palette')} title={t('shell.palette')} onClick={onOpenPalette}>
          <span className="mono" aria-hidden="true">^K</span>
        </IconButton>
        <IconButton
          label={t('shell.theme')}
          title={t('shell.theme')}
          buttonRef={themeButtonRef}
          onClick={() => {
            const box = themeButtonRef.current?.getBoundingClientRect();
            themeRevealAt(
              box ? box.left + box.width / 2 : window.innerWidth - 120,
              box ? box.top + box.height / 2 : 44,
            );
          }}
        >
          <Icon name={resolvedTheme === 'dark' ? 'moon' : 'sun'} size={18} />
        </IconButton>
        <IconButton label={t('shell.language')} title={t('shell.language')} onClick={switchLanguage}>
          <span className="mono" aria-hidden="true">{locale === 'ko' ? t('shell.localeEn') : t('shell.localeKo')}</span>
        </IconButton>
      </div>
    </header>
  );
}
