import { useLocale } from './i18n/index.ts';
import type { TimelineItem } from './timeline';

type ApprovalItem = Extract<TimelineItem, { kind: 'approval' }>;

const basename = (path: string) => path.replace(/\\/g, '/').split('/').pop() ?? path;

/** The case or file a request was about, from its own arguments; nothing when it names none. */
function targetOf(item: ApprovalItem): string {
  const args = item.request.args;
  for (const key of ['destination_rel', 'path', 'case_path', 'source_rel']) {
    const value = args[key];
    if (typeof value === 'string' && value) return basename(value);
  }
  return '';
}

/** Requests that can no longer be approved, in one read-only row; opening it lists them without controls. */
export default function ClosedApprovals({ items, open = false }: { readonly items: readonly ApprovalItem[]; readonly open?: boolean }) {
  const { t, locale } = useLocale();
  return (
    <details className="closed-approvals" open={open || undefined}>
      <summary>{t(items.length === 1 ? 'approval.closedOne' : 'approval.closedMany', { count: items.length })}</summary>
      <ul>
        {items.map((item) => {
          const headKey = `approval.head.${item.request.name}`;
          const head = t(headKey);
          const target = targetOf(item);
          const when = typeof item.request.expires_at === 'number'
            ? new Date(item.request.expires_at * 1000).toLocaleString(locale === 'en' ? 'en-US' : 'ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
            : '';
          return (
            <li key={item.id}>
              <span className="closed-approvals-tool">{head === headKey ? item.request.name : head}</span>
              {target && <span className="closed-approvals-target">{target}</span>}
              <span className="closed-approvals-reason">{t(item.resolution === 'context-expired' ? 'approval.closedReasonContext' : 'approval.closedReasonTime')}</span>
              {when && <time className="closed-approvals-time">{when}</time>}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
