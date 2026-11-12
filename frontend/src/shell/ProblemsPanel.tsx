import { useState, useSyncExternalStore } from 'react';
import { useLocale } from '../i18n/index.ts';
import { PixelIcon, type PixelIconName } from '../ui/PixelIcon';
import {
  focusTopologyNode,
  getCaseProblemsSnapshot,
  subscribeCaseProblems,
  type CaseProblem,
} from './caseProblems';

const SHOW_ALL_AFTER = 8;

function ProblemRow({ problem, onFocus }: { readonly problem: CaseProblem; readonly onFocus: (nodeId: string) => void }) {
  const { t } = useLocale();
  const icon: PixelIconName = problem.severity === 'error' ? 'close' : problem.severity === 'warning' ? 'warning' : 'node';
  const body = (
    <>
      <PixelIcon name={icon} size={18} />
      <span>
        <b className="wb-problem-title">{problem.title}</b>
        {problem.detail && <span className="wb-problem-detail">{problem.detail}</span>}
      </span>
    </>
  );
  if (!problem.nodeId) {
    return <li className={`wb-problem is-${problem.severity}`}>{body}</li>;
  }
  const nodeId = problem.nodeId;
  return (
    <li className={`wb-problem is-${problem.severity}`}>
      <button
        type="button"
        className="wb-problem-link"
        onClick={() => onFocus(nodeId)}
        aria-label={t('problems.focusNode', { node: nodeId }) ?? `Show node ${nodeId} on the topology map`}
      >
        {body}
      </button>
    </li>
  );
}

export default function ProblemsPanel({ onFocusNode }: { readonly onFocusNode: (nodeId: string) => void }) {
  const { t } = useLocale();
  const problems = useSyncExternalStore(subscribeCaseProblems, getCaseProblemsSnapshot);
  const [showAll, setShowAll] = useState(false);
  const collapsed = !showAll && problems.length > SHOW_ALL_AFTER;
  const visible = collapsed ? problems.slice(0, SHOW_ALL_AFTER) : problems;
  const focus = (nodeId: string) => {
    window.dispatchEvent(focusTopologyNode(nodeId));
    onFocusNode(nodeId);
  };
  if (problems.length === 0) {
    return <p className="wb-panel-empty">{t('shell.problemsEmpty')}</p>;
  }
  return (
    <div className="wb-problems">
      <ul className="wb-problem-list">
        {visible.map((problem) => (
          <ProblemRow key={problem.id} problem={problem} onFocus={focus} />
        ))}
      </ul>
      {collapsed ? (
        <button type="button" className="wb-problems-show-all" onClick={() => setShowAll(true)}>
          {t('problems.showAll', { count: problems.length }) ?? `Show all ${problems.length} issues`}
        </button>
      ) : (
        problems.length > SHOW_ALL_AFTER && (
          <button type="button" className="wb-problems-show-all" onClick={() => setShowAll(false)}>
            {t('problems.showLess') ?? 'Show less'}
          </button>
        )
      )}
    </div>
  );
}
