import type {
  GenkeyReviewPresentation,
  InspectionPresentation,
  PvtInspectionPresentation,
} from './inspectionPresentation';
import { useLocale } from './i18n/index.ts';

function GenkeyReview({ presentation }: { readonly presentation: GenkeyReviewPresentation }) {
  const { t } = useLocale();
  return (
    <div className="evidence-inspection">
      <header className={`inspection-head ${presentation.good ? 'is-good' : 'is-attention'}`}>
        <div>
          <span className="inspection-kicker">{t('inspect.genkeyReview')}</span>
          <h4>{presentation.title}</h4>
          <p>{presentation.detail}</p>
        </div>
        <strong>{presentation.good ? 'READY' : 'REVIEW'}</strong>
      </header>
      <div className="inspection-checks">
        {presentation.checks.map((check, index) => (
          <article key={check.label}>
            <span className="inspection-index">{String(index + 1).padStart(2, '0')}</span>
            <div><strong>{check.label}</strong><p>{check.detail}</p></div>
            <span className="inspection-state">{check.state}</span>
          </article>
        ))}
      </div>
      <details className="evidence-audit inspection-audit">
        <summary>{t('inspect.techBasis')}</summary>
        {presentation.source && <p className="inspection-source"><span>{t('inspect.sourceLabel') ?? '출처'}</span><code>{presentation.source}</code></p>}
        {presentation.checks.map((check) => check.report && (
          <details className="inspection-report" key={check.label}>
            <summary>{t('inspect.reportSummary', { label: check.label }) ?? `${check.label} 보고서`}</summary>
            <pre>{check.report}</pre>
          </details>
        ))}
      </details>
    </div>
  );
}

function PvtInspection({ presentation }: { readonly presentation: PvtInspectionPresentation }) {
  const { t } = useLocale();
  return (
    <div className="evidence-inspection pvt-inspection">
      <header className={`inspection-head ${presentation.good ? 'is-good' : 'is-attention'}`}>
        <div>
          <span className="inspection-kicker">PVT TABLE</span>
          <h4>{presentation.title}</h4>
          <p>{t('inspect.pvtLine', { label: presentation.label, phase: presentation.phase, formulation: presentation.formulation })}</p>
        </div>
        <strong>{presentation.good ? 'VALID' : 'REVIEW'}</strong>
      </header>
      <div className="pvt-ledger">
        <section className="pvt-composition" aria-label={t('inspect.pvtComposition')}>
          <h5>{t('inspect.pvtComposition')}</h5>
          <div className="pvt-components">
            {presentation.components.map((component) => (
              <article key={component.name}>
                <strong>{component.name}</strong>
                <span>{component.fraction}</span>
                {component.molarMass && <small>MW {component.molarMass}</small>}
              </article>
            ))}
          </div>
        </section>
        <dl className="pvt-metrics">
          {presentation.metrics.map((metric) => (
            <div key={metric.label}>
              <dt>{metric.label}</dt>
              <dd>{metric.value}{metric.unit && <small>{metric.unit}</small>}</dd>
              {metric.note && <span>{metric.note}</span>}
            </div>
          ))}
        </dl>
      </div>
      {(presentation.errorCount > 0 || presentation.warningCount > 0) && (
        <p className="inspection-notice">
          {presentation.errorCount} {t('inspect.validationWord') ?? 'validation'} {presentation.errorCount === 1 ? t('inspect.issueError_one') ?? 'error' : t('inspect.issueError_other') ?? 'errors'} ·{' '}
          {presentation.warningCount} {presentation.warningCount === 1 ? t('inspect.issueWarning_one') ?? 'warning' : t('inspect.issueWarning_other') ?? 'warnings'}
        </p>
      )}
      <details className="evidence-audit inspection-audit">
        <summary>{t('inspect.techEvidence')}</summary>
        <pre>{presentation.rawSummary}</pre>
      </details>
    </div>
  );
}

export default function InspectionEvidence({ presentation }: { readonly presentation: InspectionPresentation }) {
  return presentation.kind === 'genkey'
    ? <GenkeyReview presentation={presentation} />
    : <PvtInspection presentation={presentation} />;
}
