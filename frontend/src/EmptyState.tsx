import type { ReactNode } from 'react';
import { ExampleGallery } from './ExampleGallery';
import { useLocale } from './i18n/index.ts';
import type { I18nKey, TranslateFn } from './i18n/index.ts';

type StarterGroup = 'Workspace' | 'Run' | 'Results';

type Starter = {
  readonly group: StarterGroup;
  readonly label: string;
  readonly prompt: string;
};

const GROUPS: readonly StarterGroup[] = ['Workspace', 'Run', 'Results'];
const GROUP_NOTE_KEYS: Readonly<Record<StarterGroup, I18nKey>> = {
  Workspace: 'empty.groupNote.workspace',
  Run: 'empty.groupNote.run',
  Results: 'empty.groupNote.results',
};

type StarterId = 'inspectCase' | 'shortTrial' | 'haltCause' | 'newCase' | 'compareRuns' | 'keywordMeaning';

type RoutedStarter = Starter & { readonly id: StarterId };

function startersFor(caseContext: string): readonly RoutedStarter[] {
  return [
    { id: 'inspectCase', group: 'Workspace', label: '사례 검사하기', prompt: `검사 대상: ${caseContext}. 토폴로지를 보여주세요.` },
    { id: 'shortTrial', group: 'Run', label: '짧게 시험 실행', prompt: `짧은 시험 실행을 ${caseContext} 기준으로 미리 보여주고, 제 승인을 기다리세요.` },
    { id: 'haltCause', group: 'Run', label: '중단 원인 찾기', prompt: 'Workspace의 최신 .out 로그를 읽고 왜 멈췄는지 설명하세요.' },
    { id: 'newCase', group: 'Workspace', label: '새 사례 만들기', prompt: 'CO2 파이프라인 사례를 새로 짜주세요: 입구부터 파이프를 거쳐 출구까지.' },
    { id: 'compareRuns', group: 'Results', label: '두 실행 비교하기', prompt: 'Workspace의 최신 .tpl/.ppl 출력 두 개를 비교하세요.' },
    { id: 'keywordMeaning', group: 'Workspace', label: '키워드 뜻 묻기', prompt: 'OLGA genkey에서 FLOWPATH 키워드는 무엇을 정하나요?' }
  ];
}

function starterLabel(t: TranslateFn, starter: RoutedStarter): string {
  return t(`empty.starter.${starter.id}Label`);
}

function starterPrompt(t: TranslateFn, starter: RoutedStarter, caseContext: string): string {
  return t(`empty.starter.${starter.id}Prompt`, { caseContext });
}

export default function EmptyState({
  activeCaseName,
  workspaceCaseCount,
  onPick,
  disabled,
  children,
}: {
  readonly activeCaseName: string | null;
  readonly workspaceCaseCount: number;
  readonly onPick: (prompt: string) => void;
  readonly disabled: boolean;
  readonly children?: ReactNode;
}) {
  const { t } = useLocale();
  const caseContext = activeCaseName
    ? activeCaseName
    : workspaceCaseCount > 0
      ? t('empty.noActiveCaseNamed')
      : t('empty.noActiveCaseEmpty');
  const starters = startersFor(caseContext);

  return (
    <div className="empty-state" data-testid="empty-state">
      <div className="empty-hero">
        <div className="empty-intro">
          <h2>{t('empty.title')}</h2>
          <p className="empty-lede">{t('empty.lede')}</p>
        </div>
      </div>

      <ExampleGallery disabled={disabled} />
      {children}
      <details className="advanced-starters">
        <summary>{t('empty.quickTitle')} <span>{t('empty.quickNote')}</span></summary>
        <div className="starter-groups" aria-label={t('empty.startersAria')}>
        {GROUPS.map((group, groupIndex) => (
          <section key={group} className="starter-group" aria-label={t('empty.groupStartersAria', { group })}>
            <header className="starter-group-head">
              <span className="starter-group-index" aria-hidden="true">0{groupIndex + 1}</span>
              <span>
                <strong className="starter-group-title">{group}</strong>
                <em className="starter-group-note">{t(GROUP_NOTE_KEYS[group])}</em>
              </span>
            </header>
            <div className="starter-list">
              {starters.filter((starter) => starter.group === group).map((starter) => (
                <button
                  key={starter.id}
                  type="button"
                  className="starter"
                  onClick={() => onPick(starterPrompt(t, starter, caseContext))}
                  disabled={disabled}
                >
                  <span className="starter-copy">
                    <span className="starter-label">{starterLabel(t, starter)}</span>
                    <span className="starter-prompt">{starterPrompt(t, starter, caseContext)}</span>
                  </span>
                  <span className="starter-arrow" aria-hidden="true">↗</span>
                </button>
              ))}
            </div>
          </section>
        ))}
        </div>
      </details>
    </div>
  );
}
