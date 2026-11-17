import { useRef, useState } from 'react';
import { createRequestEpoch } from './requestEpoch';
import FindingsCriterionFields, { KIND_LABEL_KEYS, type CriterionFieldKey, type CriterionKind } from './FindingsCriterionFields';
import { createNativeDialogRequestId } from './nativeDialogRequest';
import { revealSavedReport, saveArtifactAs } from './nativeDialogApi';
import { createFindingsReport, evaluateFindings, type FindingJudgement } from './resultApi';
import { useLocale } from './i18n/index.ts';
import type { ResultFile, ResultVar } from './resultContracts';
import { sessionFigures } from './sessionFigures';
import { Button } from './ui/Button';

const REQUIRED_VARIABLE: Readonly<Record<CriterionKind, string>> = {
  pressure_drop: 'PT',
  liqc: 'HOL',
  slugging: 'HOL',
  wax_hydrate: 'TM',
};

const KIND_FILE_HINT_KEYS: Readonly<Record<CriterionKind, string>> = {
  pressure_drop: 'findings.hintPressureDrop',
  liqc: 'findings.hintLiqc',
  slugging: 'findings.hintSlugging',
  wax_hydrate: 'findings.hintWax',
};

function uniquePositions(variables: readonly ResultVar[], name: string): string[] {
  const seen = new Set<string>();
  for (const item of variables) {
    if (item.variable === name && item.position && !seen.has(item.position)) seen.add(item.position);
  }
  return [...seen];
}

function formatMeasured(measured: Readonly<Record<string, unknown>> | undefined): string {
  if (!measured) return '';
  return Object.entries(measured)
    .filter(([, value]) => value !== null && value !== undefined && typeof value !== 'object')
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(' · ');
}

function formatThreshold(threshold: Readonly<Record<string, unknown>> | undefined): string {
  if (!threshold) return '';
  return Object.entries(threshold)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(' · ');
}

export default function FindingsPanel({
  selected, variables, branches, genkeyHint, workspaceRoot, workspaceCases,
}: {
  readonly selected: ResultFile;
  readonly variables: readonly ResultVar[];
  readonly branches: readonly string[];
  readonly genkeyHint: string | null;
  readonly workspaceRoot?: string;
  readonly workspaceCases?: readonly { readonly name: string; readonly rel: string }[];
}) {
  const [kind, setKind] = useState<CriterionKind>('pressure_drop');
  const [fields, setFields] = useState<Record<CriterionFieldKey, string>>({
    inlet: '', outlet: '', maxDrop: '', unit: '',
    branch: '', pipe: '', maxCount: '', hydrateTemp: '', waxTemp: '', maxLitres: '',
  });
  const [genkey, setGenkey] = useState(genkeyHint ?? '');
  const [busy, setBusy] = useState(false);
  const { t } = useLocale();
  const [error, setError] = useState('');
  const [verdict, setVerdict] = useState<FindingJudgement | null>(null);
  const [shownVerdicts, setShownVerdicts] = useState<readonly FindingJudgement[]>([]);
  const [pendingNote, setPendingNote] = useState('');
  const [reportBusy, setReportBusy] = useState(false);
  const [reportNote, setReportNote] = useState('');
  const [savedFile, setSavedFile] = useState('');
  const [revealId, setRevealId] = useState('');
  const judgeRequestRef = useRef(createRequestEpoch());
  const reportRequestRef = useRef(createRequestEpoch());

  function invalidateRequests() {
    judgeRequestRef.current.invalidate();
    reportRequestRef.current.invalidate();
  }

  const required = REQUIRED_VARIABLE[kind];
  const hasRequired = variables.some((item) => item.variable === required);
  const positions = uniquePositions(variables, 'PT');
  const branchOptions = branches.length > 0 ? [...branches] : uniquePositions(variables, required);
  const pipeOptions = uniquePositions(variables, 'HOL');
  const variableUnit = variables.find((item) => item.variable === required)?.unit ?? '';
  const caseOptions = (workspaceCases ?? []).filter((item) => item.name.endsWith('.genkey'));
  const genkeyChoices = genkey && !caseOptions.some((item) => item.rel === genkey)
    ? [{ name: genkey, rel: genkey }, ...caseOptions]
    : caseOptions;
  const missingBranch = (kind === 'slugging' || kind === 'wax_hydrate' || kind === 'liqc') && branchOptions.length === 0 && fields.branch.trim() === '';

  function onField(key: CriterionFieldKey, value: string) {
    invalidateRequests();
    setFields((prev) => ({ ...prev, [key]: value }));
    setVerdict(null);
    setShownVerdicts([]);
  }

  function onGenkeyChange(value: string) {
    invalidateRequests();
    setGenkey(value);
    setVerdict(null);
    setShownVerdicts([]);
  }

  function onKindChange(next: CriterionKind) {
    invalidateRequests();
    setKind(next);
    setVerdict(null);
    setShownVerdicts([]);
    setPendingNote('');
    setError('');
  }

  function criterionParams(): Record<string, unknown> | null {
    const file = selected.id;
    if (kind === 'pressure_drop') {
      if (!fields.inlet || !fields.outlet || fields.maxDrop.trim() === '') return null;
      const limit = Number(fields.maxDrop);
      if (!Number.isFinite(limit)) return null;
      return { tpl: file, inlet_position: fields.inlet, outlet_position: fields.outlet, max_drop: limit, ...(fields.unit.trim() ? { unit: fields.unit.trim() } : {}) };
    }
    if (kind === 'slugging') {
      if (!fields.branch.trim() || fields.maxCount.trim() === '') return null;
      const limit = Number(fields.maxCount);
      if (!Number.isFinite(limit)) return null;
      return { ppl: file, branch: fields.branch.trim(), max_slug_count: limit };
    }
    if (kind === 'wax_hydrate') {
      if (!fields.branch.trim() || fields.hydrateTemp.trim() === '' || fields.waxTemp.trim() === '') return null;
      const hydrate = Number(fields.hydrateTemp);
      const wax = Number(fields.waxTemp);
      if (!Number.isFinite(hydrate) || !Number.isFinite(wax)) return null;
      return { file, branch: fields.branch.trim(), hydrate_temp: hydrate, wax_temp: wax };
    }
    if (!fields.branch.trim() || fields.pipe.trim() === '' || fields.maxLitres.trim() === '' || genkey.trim() === '') return null;
    const limit = Number(fields.maxLitres);
    if (!Number.isFinite(limit)) return null;
    return { ppl: file, genkey: genkey.trim(), flowpath: fields.branch.trim(), pipe: fields.pipe.trim(), max_litres: limit };
  }

  async function judge() {
    const params = criterionParams();
    if (!params) {
      setPendingNote(t('findings.fillToJudge') ?? '빈 칸을 채우면 판정할 수 있어요.');
      setVerdict(null);
      setShownVerdicts([]);
      return;
    }
    const requestId = judgeRequestRef.current.begin();
    setBusy(true);
    setError('');
    setPendingNote('');
    setVerdict(null);
    setShownVerdicts([]);
    try {
      const response = await evaluateFindings([{ kind, params }]);
      if (!judgeRequestRef.current.isCurrent(requestId)) return;
      setShownVerdicts(response.pending.length > 0 ? response.pending : response.judgements);
      if (response.pending.length > 0) {
        const missing = response.pending[0].missing ?? [];
        setPendingNote(t('findings.stillNeed', { missing: missing.join(', ') }) ?? `아직 ${missing.join(', ')} 입력이 필요해요.`);
        return;
      }
      setVerdict(response.judgements[0] ?? null);
    } catch (cause) {
      if (judgeRequestRef.current.isCurrent(requestId)) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      setBusy(false);
    }
  }

  async function writeReport() {
    const caseFile = genkey.trim() || genkeyHint || '';
    if (!caseFile) {
      setError(t('findings.needCaseFile') ?? '사례 파일이 필요해요.');
      return;
    }
    const requestId = reportRequestRef.current.begin();
    setReportBusy(true);
    setError('');
    setReportNote('');
    setSavedFile('');
    setRevealId('');
    try {
      const variableCodes = [...new Set(variables.map((item) => item.variable).filter(Boolean))];
      const report = await createFindingsReport({
        case_file: caseFile,
        results_file: selected.id,
        verdicts: shownVerdicts,
        figures: sessionFigures(),
        variables: variableCodes,
        ...(selected.run_id ? { run_id: selected.run_id } : {}),
      });
      if (!reportRequestRef.current.isCurrent(requestId)) return;
      const nativeRequestId = createNativeDialogRequestId();
      const result = await saveArtifactAs(nativeRequestId, report.artifact, workspaceRoot);
      if (!reportRequestRef.current.isCurrent(requestId)) return;
      if (result.status === 'cancelled') {
        setReportNote(t('findings.saveCancelled') ?? '저장을 취소했습니다');
        return;
      }
      if (result.status === 'selected') {
        setSavedFile(result.basename);
        setRevealId(result.reveal_id ?? '');
        return;
      }
      setReportNote(result.reason);
    } catch (cause) {
      if (reportRequestRef.current.isCurrent(requestId)) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      setReportBusy(false);
    }
  }

  async function showInFolder() {
    if (!revealId) return;
    try {
      await revealSavedReport(revealId);
    } catch {
      setReportNote(t('findings.folderFailed') ?? '폴더를 열지 못했어요.');
    }
  }

  return (
    <section className="findings-panel" aria-label={t('findings.title')}>
      <h3 className="findings-title">{t('findings.title')}</h3>
      <p className="findings-lede">{t('findings.lede')}</p>

      <FindingsCriterionFields
        kind={kind}
        glossaryTerm={required}
        positions={positions}
        branchOptions={branchOptions}
        pipeOptions={pipeOptions}
        values={fields}
        variableUnit={variableUnit}
        onKindChange={onKindChange}
        onField={onField}
      />

      {!hasRequired && (
        <p className="findings-note">{t('findings.noVar', { required }) ?? `이 파일에는 ${required}가 없어요. ${required}를 출력에 추가하세요.`}</p>
      )}

      <label className="findings-field">
        <span>{t('findings.caseFileLabel') ?? '사례 파일(.genkey)'}</span>
        <select value={genkey} onChange={(event) => onGenkeyChange(event.target.value)}>
          <option value="">{t('findings.chooseCase') ?? '사례 선택'}</option>
          {genkeyChoices.map((item) => <option key={item.rel} value={item.rel}>{item.name}</option>)}
        </select>
      </label>

      {missingBranch && (
        <p className="findings-note">{t('findings.pickBranch', { hint: t(KIND_FILE_HINT_KEYS[kind]) }) ?? `브랜치를 고르면 판정할 수 있어요. ${t(KIND_FILE_HINT_KEYS[kind])} 브랜치를 고르세요.`}</p>
      )}

      <div className="findings-actions">
        <Button variant="primary" onClick={() => { void judge(); }} busy={busy} busyLabel={t('findings.judging')}>{t('findings.judge')}</Button>
        <Button variant="secondary" onClick={() => { void writeReport(); }} busy={reportBusy} busyLabel={t('findings.makingReport')}>{t('findings.makeReport')}</Button>
        {revealId && (
          <Button variant="secondary" onClick={() => { void showInFolder(); }}>{t('findings.showInFolder') ?? '폴더에서 보기'}</Button>
        )}
      </div>

      {pendingNote && <p className="findings-note" role="status">{pendingNote}</p>}
      {reportNote && <p className="findings-note" role="status">{reportNote}</p>}
      {savedFile && <p className="findings-note" role="status">{t('findings.savedFile') ?? '저장됨:'} {savedFile}</p>}
      {error && <p className="findings-error" role="alert">{error}</p>}
      {verdict && (
        <div className={`findings-verdict findings-${(verdict.verdict ?? '').toLowerCase()}`} role="status">
          <strong>{verdict.verdict === 'PASS' ? t('findings.passState') ?? '통과' : verdict.verdict === 'FAIL' ? t('findings.failState') ?? '미달' : verdict.verdict}</strong>
          <span>{t(KIND_LABEL_KEYS[kind as CriterionKind])} · {formatThreshold(verdict.threshold)}</span>
          {verdict.measured && <span>{formatMeasured(verdict.measured)}</span>}
          {verdict.source_file && (
            <span>{t('findings.evidence') ?? '근거:'} {verdict.source_file}{verdict.source_sha256 ? t('findings.evidenceSha', { sha: verdict.source_sha256.slice(0, 12) }) ?? ` · sha ${verdict.source_sha256.slice(0, 12)}` : ''}{verdict.mapping ? ` · ${Object.values(verdict.mapping).filter((value) => typeof value === 'string').join(' · ')}` : ''}</span>
          )}
        </div>
      )}
    </section>
  );
}
