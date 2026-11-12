import { Fragment } from 'react';
import { useLocale } from './i18n/index.ts';
import type { PlanStepRow } from './planApproval.mjs';

/** A started run is not a finished one: its step reads "started", never "done". */
function stateKey(row: PlanStepRow): string {
  return row.kind === 'run_execute' && row.state === 'done' ? 'started' : row.state;
}

/** The ordered rows of a plan card: what each step does, and how far it got. */
export default function PlanSteps({ rows }: { readonly rows: readonly PlanStepRow[] }) {
  const { t } = useLocale();
  return (
    <ol className="approval-plan-steps" aria-label={t('approval.plan.stepsLabel')}>
      {rows.map((row) => (
        <li key={row.index} className="approval-plan-step" data-state={row.state}>
          <p className="approval-plan-step-head">
            <strong>{t('approval.plan.step', { n: String(row.index) })}</strong>
            <span>{t(`approval.plan.kind.${row.kind}`)}</span>
            {row.state !== 'waiting' && <span className="approval-plan-state">{t(`approval.plan.state.${stateKey(row)}`)}</span>}
          </p>
          <dl>
            {row.fields.map((field, position) => (
              <Fragment key={`${field.key}-${position}`}>
                <dt>{t(`approval.field.${field.key}`)}</dt>
                <dd>{field.value}{field.unit ? ` ${field.unit}` : ''}</dd>
              </Fragment>
            ))}
            {row.boundTo !== null && row.unknown.map((key) => (
              <Fragment key={key}>
                <dt>{t(`approval.field.${key}`)}</dt>
                <dd className="approval-plan-unknown">
                  {key === 'run_case' ? t('approval.plan.caseFromStep', { step: String(row.boundTo) }) : t('approval.plan.chosenAtRun')}
                </dd>
              </Fragment>
            ))}
          </dl>
          {row.inputs.length > 0 && (
            <section className="approval-plan-inputs" aria-label={t('approval.inputsTitle')}>
              {row.inputs.map((group) => (
                <div key={group.group} className="approval-input-group">
                  <p className="approval-input-group-title">{group.group}</p>
                  <dl>
                    {group.items.map((item) => (
                      <div key={item.name} className="approval-input-row">
                        <dt>{item.name}</dt>
                        <dd>{item.value}{item.unit ? ` ${item.unit}` : ''}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ))}
            </section>
          )}
          {row.error && <p className="approval-plan-error">{t('approval.plan.reason', { reason: row.error })}</p>}
        </li>
      ))}
    </ol>
  );
}
