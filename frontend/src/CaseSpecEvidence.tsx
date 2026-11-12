import { issueText } from './caseSpecIssue.ts';
import { useLocale } from './i18n/index.ts';

type Result = Record<string, unknown>;

function record(value: unknown): Result | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Result : null;
}

function value(value: unknown, missing: string): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return missing;
}

function IssueList({ title, issues, missing, locale }: { readonly title: string; readonly issues: unknown; readonly missing: string; readonly locale: string }) {
  if (!Array.isArray(issues) || issues.length === 0) return null;
  return (
    <section className="evidence-issues">
      <strong>{title}</strong>
      <ul className="evidence-diff-list">
        {issues.slice(0, 12).map((issue, index) => {
          return <li key={index}>{issueText(issue, locale, missing)}</li>;
        })}
      </ul>
    </section>
  );
}

export default function CaseSpecEvidence({ result }: { readonly result: Result }) {
  const { t, locale } = useLocale();
  const valid = result.valid === true;
  const publishable = result.publishable === true;
  const validation = record(result.validation);
  const compileClean = validation ? validation.clean === true : null;
  const topology = record(result.topology);
  const nodes = Array.isArray(topology?.nodes) ? topology.nodes : [];
  const edges = Array.isArray(topology?.edges) ? topology.edges : [];
  const compiledGeometry = Array.isArray(result.geometry) ? result.geometry : [];
  const normalized = record(result.normalized);
  const plannedNodes = Array.isArray(normalized?.nodes) ? normalized.nodes.length : 0;
  const plannedFlowpaths = Array.isArray(normalized?.flowpaths) ? normalized.flowpaths.length : 0;
  // A validate-only result carries the normalized plan but no compiled geometry.
  const plannedGeometry = (Array.isArray(normalized?.flowpaths) ? normalized.flowpaths : []).flatMap((item) => {
    const flowpath = record(item);
    const pipes = Array.isArray(flowpath?.pipes) ? flowpath.pipes : [];
    return pipes.map((entry) => {
      const pipe = record(entry);
      return { flowpath: flowpath?.label, pipe: pipe?.label, diameter_m: pipe?.diameter_m, sections: pipe?.sections };
    });
  });
  const geometry: unknown[] = compiledGeometry.length > 0 ? compiledGeometry : plannedGeometry;
  const plannedSections = plannedGeometry.every((pipe) => typeof pipe.sections === 'number')
    ? plannedGeometry.reduce((sum, pipe) => sum + (pipe.sections as number), 0)
    : null;
  const diagnostics = Array.isArray(validation?.diagnostics) ? validation.diagnostics : [];
  const good = valid && compileClean !== false;
  const missing = t('casespec.valueUnavailable');
  const sectionCount = typeof result.section_count === 'number'
    ? result.section_count
    : compiledGeometry.length === 0 && plannedGeometry.length > 0 ? plannedSections : null;
  return (
    <div className="evidence-lifecycle casespec-evidence">
      <header className={`evidence-outcome ${good ? 'is-good' : 'is-attention'}`}>
        <div>
          <strong>{good ? t('casespec.validTitle') ?? '사례 명세가 맞습니다' : t('casespec.invalidTitle') ?? '사례 명세를 확인하세요'}</strong>
          <p className="evidence-prose">
            {good
              ? publishable
                ? t('casespec.publishableDetail') ?? '명세가 맞고 서버가 게시 가능으로 표시했습니다.'
                : t('casespec.cleanDetail') ?? '검증은 깨끗합니다. 검토된 거래를 직접 승인하기 전에는 게시할 수 없습니다.'
              : t('casespec.missingDetail') ?? '사례 파일을 쓰지 않았습니다. 아래 검증 내용을 해결하고 다시 검증하세요.'}
          </p>
        </div>
      </header>
      <dl className="evidence-metrics" aria-label={t('casespec.summary')}>
        <div><dt>{t('casespec.conn')}</dt><dd>{t('casespec.nodesPipes', { nodes: nodes.length || plannedNodes, pipes: edges.length || plannedFlowpaths })}</dd></div>
        <div><dt>{t('casespec.shape')}</dt><dd>{sectionCount === null
          ? t('casespec.pipesSectionsUnavailable', { pipes: geometry.length })
          : t('casespec.pipesSections', { pipes: geometry.length, sections: sectionCount })}</dd></div>
        <div><dt>{t('casespec.syntax')}</dt><dd>{validation ? (validation.parser_clean === true ? t('casespec.pass') : t('casespec.review')) : t('casespec.unknown')}</dd></div>
        <div><dt>{t('casespec.values')}</dt><dd>{validation ? (validation.validator_clean === true ? t('casespec.pass') : t('casespec.review')) : t('casespec.unknown')}</dd></div>
      </dl>
      {geometry.length > 0 && (
        <div className="evidence-table-viewport" tabIndex={0} aria-label={t('casespec.geometryAria') ?? 'Compiled pipe geometry'}>
          <table className="evidence-table">
            <thead><tr><th>{t('casespec.colFlowpath') ?? 'Flowpath'}</th><th>{t('casespec.colPipe') ?? 'Pipe'}</th><th>{t('casespec.colDiameter') ?? 'Diameter'}</th><th>{t('casespec.colSections') ?? 'Sections'}</th></tr></thead>
            <tbody>
              {geometry.slice(0, 12).map((entry, index) => {
                const pipe = record(entry);
                const diameter = typeof pipe?.diameter_m === 'number' ? pipe.diameter_m : null;
                return (
                  <tr key={`${value(pipe?.flowpath, missing)}:${value(pipe?.pipe, missing)}:${index}`}>
                    <th scope="row">{value(pipe?.flowpath, missing)}</th>
                    <td>{value(pipe?.pipe, missing)}</td>
                    <td>{diameter === null ? missing : <>{diameter} m</>}</td>
                    <td>{value(pipe?.sections, missing)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <IssueList title={t('casespec.errors')} issues={result.errors} missing={missing} locale={locale} />
      <IssueList title={t('casespec.warnings')} issues={result.warnings} missing={missing} locale={locale} />
      {diagnostics.length > 0 && <IssueList title={t('casespec.compilerTitle') ?? '컴파일러 알림'} issues={diagnostics} missing={missing} locale={locale} />}
      <details className="evidence-audit">
        <summary>{t('casespec.audit')}</summary>
        <dl>
          {['spec_hash', 'compiled_hash', 'companion_status', 'source_mutated', 'publishable'].map((key) => (
            key in result && <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd className="evidence-value-technical">{value(result[key], missing)}</dd></div>
          ))}
        </dl>
      </details>
    </div>
  );
}
