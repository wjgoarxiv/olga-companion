import { useEffect, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import GlossaryTerm from './GlossaryTerm';
import { apiFetch } from './sessionTransport';
import { fetchWorkspace } from './workspaceApi';
import { Button } from './ui/Button';

type IntakeItem = {
  readonly key: string;
  readonly label: string;
  readonly unit: string;
  readonly required: boolean;
  readonly values?: readonly string[];
};

type IntakeGroup = {
  readonly id: string;
  readonly title: string;
  readonly items: readonly IntakeItem[];
};

const TAB_EXPLAINER = 'PVT 표(.tab)는 유체 물성 프로그램(예: Multiflash, PVTsim)에서 만든 파일입니다. 앱은 유체 데이터를 만들지 않습니다.';

const GROUP_NOTE_KEYS: Readonly<Record<string, string>> = {
  fluid: 'intake.groupNote.fluid',
  boundary: 'intake.groupNote.boundary',
  geometry: 'intake.groupNote.geometry',
  thermal: 'intake.groupNote.thermal',
  equipment: 'intake.groupNote.equipment',
  outputs: 'intake.groupNote.outputs',
  time: 'intake.groupNote.time',
};

const ITEM_COPY_KEYS: Readonly<Record<string, { readonly why: string; readonly where: string }>> = {
  'fluid.pvt_reference': { why: 'intake.item.fluid.pvt_reference.why', where: 'intake.item.fluid.pvt_reference.where' },
  'fluid.fluid_label': { why: 'intake.item.fluid.fluid_label.why', where: 'intake.item.fluid.fluid_label.where' },
  'boundary.source_pressure': { why: 'intake.item.boundary.source_pressure.why', where: 'intake.item.boundary.source_pressure.where' },
  'boundary.source_temperature': { why: 'intake.item.boundary.source_temperature.why', where: 'intake.item.boundary.source_temperature.where' },
  'boundary.sink_pressure': { why: 'intake.item.boundary.sink_pressure.why', where: 'intake.item.boundary.sink_pressure.where' },
  'boundary.sink_temperature': { why: 'intake.item.boundary.sink_temperature.why', where: 'intake.item.boundary.sink_temperature.where' },
  'boundary.massflow_rate': { why: 'intake.item.boundary.massflow_rate.why', where: 'intake.item.boundary.massflow_rate.where' },
  'boundary.massflow_temperature': { why: 'intake.item.boundary.massflow_temperature.why', where: 'intake.item.boundary.massflow_temperature.where' },
  'geometry.pipe_path': { why: 'intake.item.geometry.pipe_path.why', where: 'intake.item.geometry.pipe_path.where' },
  'geometry.diameter': { why: 'intake.item.geometry.diameter.why', where: 'intake.item.geometry.diameter.where' },
  'geometry.roughness': { why: 'intake.item.geometry.roughness.why', where: 'intake.item.geometry.roughness.where' },
  'geometry.sections': { why: 'intake.item.geometry.sections.why', where: 'intake.item.geometry.sections.where' },
  'thermal.model': { why: 'intake.item.thermal.model.why', where: 'intake.item.thermal.model.where' },
  'thermal.ambient_temperature': { why: 'intake.item.thermal.ambient_temperature.why', where: 'intake.item.thermal.ambient_temperature.where' },
  'thermal.outer_coefficient': { why: 'intake.item.thermal.outer_coefficient.why', where: 'intake.item.thermal.outer_coefficient.where' },
  'thermal.wall': { why: 'intake.item.thermal.wall.why', where: 'intake.item.thermal.wall.where' },
  'equipment.valve': { why: 'intake.item.equipment.valve.why', where: 'intake.item.equipment.valve.where' },
  'outputs.outputs': { why: 'intake.item.outputs.outputs.why', where: 'intake.item.outputs.outputs.where' },
  'time.end_time_s': { why: 'intake.item.time.end_time_s.why', where: 'intake.item.time.end_time_s.where' },
  'time.trend_interval_s': { why: 'intake.item.time.trend_interval_s.why', where: 'intake.item.time.trend_interval_s.where' },
  'time.profile_interval_s': { why: 'intake.item.time.profile_interval_s.why', where: 'intake.item.time.profile_interval_s.where' },
  'time.output_interval_s': { why: 'intake.item.time.output_interval_s.why', where: 'intake.item.time.output_interval_s.where' },
  'time.max_dt_s': { why: 'intake.item.time.max_dt_s.why', where: 'intake.item.time.max_dt_s.where' },
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function nonEmpty(value: unknown): boolean {
  if (typeof value === 'string') return value.trim() !== '';
  if (typeof value === 'number') return Number.isFinite(value);
  return value !== null && value !== undefined;
}

function nodeWith(node: unknown, field: string): boolean {
  return isRecord(node) && nonEmpty(node[field]);
}

/** Presence in the latest validate/compile evidence. No evidence means not given. */
export function intakeProvided(key: string, evidence: Record<string, unknown> | null): boolean {
  if (!evidence) return false;
  const nodes = Array.isArray(evidence.nodes) ? evidence.nodes : [];
  const flowpaths = Array.isArray(evidence.flowpaths) ? evidence.flowpaths : [];
  const thermal = isRecord(evidence.thermal) ? evidence.thermal : null;
  const outputs = Array.isArray(evidence.outputs) ? evidence.outputs : [];
  const integration = isRecord(evidence.integration) ? evidence.integration : null;
  const firstPipe = (() => {
    const first = flowpaths[0];
    if (!isRecord(first) || !Array.isArray(first.pipes)) return null;
    const pipe = first.pipes[0];
    return isRecord(pipe) ? pipe : null;
  })();
  switch (key) {
    case 'fluid.pvt_reference': return nonEmpty(evidence.pvt_reference);
    case 'fluid.fluid_label': return nonEmpty(evidence.fluid_label);
    case 'boundary.source_pressure': return nodes.some((node) => nodeWith(node, 'kind') && (node as Record<string, unknown>).kind === 'source' && nodeWith(node, 'pressure_pa'));
    case 'boundary.source_temperature': return nodes.some((node) => isRecord(node) && node.kind === 'source' && nodeWith(node, 'temperature_c'));
    case 'boundary.sink_pressure': return nodes.some((node) => isRecord(node) && node.kind === 'sink' && nodeWith(node, 'pressure_pa'));
    case 'boundary.sink_temperature': return nodes.some((node) => isRecord(node) && node.kind === 'sink' && nodeWith(node, 'temperature_c'));
    case 'boundary.massflow_rate':
    case 'boundary.massflow_temperature': return Array.isArray(evidence.massflow_sources) && evidence.massflow_sources.length > 0;
    case 'geometry.pipe_path': return firstPipe !== null && Array.isArray(firstPipe.centerline_m);
    case 'geometry.diameter': return firstPipe !== null && nonEmpty(firstPipe.diameter_m);
    case 'geometry.roughness': return firstPipe !== null && nonEmpty(firstPipe.roughness_m);
    case 'geometry.sections': return firstPipe !== null && nonEmpty(firstPipe.sections);
    case 'thermal.model': return thermal !== null && nonEmpty(thermal.model);
    case 'thermal.ambient_temperature': return thermal !== null && thermal.model === 'ambient_h_given' && nonEmpty(thermal.ambient_temperature_c);
    case 'thermal.outer_coefficient': return thermal !== null && thermal.model === 'ambient_h_given' && nonEmpty(thermal.outer_heat_transfer_coefficient_w_m2k);
    case 'thermal.wall': return thermal !== null && thermal.model === 'ambient_h_given' && isRecord(thermal.wall);
    case 'equipment.valve': return Array.isArray(evidence.equipment) && evidence.equipment.length > 0;
    case 'outputs.outputs': return outputs.length > 0;
    case 'time.end_time_s': return integration !== null && nonEmpty(integration.end_time_s);
    case 'time.trend_interval_s': return integration !== null && nonEmpty(integration.trend_interval_s);
    case 'time.profile_interval_s': return integration !== null && nonEmpty(integration.profile_interval_s);
    case 'time.output_interval_s': return integration !== null && nonEmpty(integration.output_interval_s);
    case 'time.max_dt_s': return integration !== null && nonEmpty(integration.max_dt_s);
    default: return false;
  }
}

export default function NewCaseChecklist({
  evidence,
  onOpenSettings,
  onOpenWorkspace,
  nativeTab = false,
}: {
  readonly evidence: Record<string, unknown> | null;
  readonly onOpenSettings: () => void;
  readonly onOpenWorkspace: () => void;
  readonly nativeTab?: boolean;
}) {
  const [groups, setGroups] = useState<readonly IntakeGroup[]>([]);
  const [tabCount, setTabCount] = useState<number | null>(null);
  const [loadError, setLoadError] = useState('');
  const { t } = useLocale();

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [requirements, workspace] = await Promise.all([
          apiFetch('/api/case-spec/requirements').then((response) => response.json()) as Promise<{ groups: IntakeGroup[] }>,
          fetchWorkspace(),
        ]);
        if (cancelled) return;
        setGroups(requirements.groups);
        setTabCount(workspace.cases.filter((entry) => entry.suffix === '.tab').length);
      } catch (cause) {
        if (!cancelled) setLoadError(cause instanceof Error ? cause.message : String(cause));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <section className="new-case-card" aria-label={t('intake.title')}>
      <h4>{t('intake.title')}</h4>
      <p className="new-case-lede">{t('intake.lede')}</p>
      {loadError && <p className="new-case-error" role="alert">{loadError}</p>}
      {groups.map((group) => (
        <div key={group.id} className="new-case-group">
          <h5>{group.title}</h5>
          {GROUP_NOTE_KEYS[group.id] && <p className="new-case-note">{t(GROUP_NOTE_KEYS[group.id])}</p>}
          <ul>
            {group.items.map((item) => {
              const copy = ITEM_COPY_KEYS[item.key];
              const provided = intakeProvided(item.key, evidence);
              return (
                <li key={item.key} className="new-case-item">
                  <span className={`new-case-status ${provided ? 'is-given' : 'is-missing'}`}>{provided ? t('intake.statusGiven') ?? '입력됨' : t('intake.statusMissing') ?? '미입력'}</span>
                  <span className="new-case-name">{item.label}{item.unit ? ` (${item.unit})` : ''}{item.required ? '' : t('intake.optionalMarker') ?? ' · 선택'}</span>
                  {copy && <span className="new-case-why">{t(copy.why)} {t('intake.sourceLabel') ?? '가져올 곳:'} {t(copy.where)}.</span>}
                  {item.values && item.values.length > 0 && (
                    <span className="new-case-values" aria-label={t('intake.valuesAria') ?? '고를 수 있는 값'}>
                      {item.values.map((value) => (
                        <GlossaryTerm key={value} term={value}><span className="new-case-value">{value}</span></GlossaryTerm>
                      ))}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      <p className="new-case-tab">{t(nativeTab ? 'intake.tabExplainer.native' : 'intake.tabExplainer') ?? TAB_EXPLAINER}</p>
      {tabCount === 0 && (
        <div className="new-case-recovery">
          <p>{t('intake.noTab') ?? 'Workspace에 .tab 파일이 없습니다. PVT 표를 Workspace에 넣은 뒤 다시 확인하세요.'}</p>
          <div className="new-case-actions">
            <Button variant="secondary" onClick={onOpenWorkspace}>{t('intake.openWorkspace') ?? 'Workspace 열기'}</Button>
            <Button onClick={onOpenSettings}>{t('intake.openSettings') ?? '설정 열기'}</Button>
          </div>
        </div>
      )}
    </section>
  );
}
