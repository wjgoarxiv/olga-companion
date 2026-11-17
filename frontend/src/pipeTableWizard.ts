/** What the read-only preview route returns for one workspace pipe table. */
export interface PipeTablePreview {
  readonly lines: readonly string[];
  readonly pipes: number;
  readonly ends: readonly { readonly node: string; readonly has_values: boolean }[];
  readonly junctions: readonly string[];
  readonly ignored_columns: readonly string[];
  readonly issues: readonly { readonly row: number | null; readonly code: string; readonly reason: string }[];
}

export interface PipeTableFile {
  readonly name: string;
  readonly rel: string;
}

export type EndKind = 'source' | 'sink';

/** One end node as the user types it: bar and °C, fractions 0–1. */
export interface EndEntry {
  readonly node: string;
  readonly kind: EndKind | '';
  readonly pressureBar: string;
  readonly temperatureC: string;
  readonly gasFraction: string;
  readonly waterFraction: string;
}

export interface Boundary {
  readonly node: string;
  readonly kind: EndKind;
  readonly pressure_pa: number;
  readonly temperature_c: number;
  readonly gas_fraction: number;
  readonly water_fraction: number;
}

// Whether the wizard dialog is on screen, so other overlays (the tutorial card) can step aside.
let wizardShown = false;
const shownListeners = new Set<() => void>();
export function markPipeTableWizardShown(shown: boolean): void {
  if (wizardShown === shown) return;
  wizardShown = shown;
  shownListeners.forEach((notify) => notify());
}
export function isPipeTableWizardShown(): boolean {
  return wizardShown;
}
export function subscribePipeTableWizardShown(notify: () => void): () => void {
  shownListeners.add(notify);
  return () => {
    shownListeners.delete(notify);
  };
}

export function blankEnd(node: string): EndEntry {
  return { node, kind: '', pressureBar: '', temperatureC: '', gasFraction: '', waterFraction: '' };
}

function number(text: string): number | null {
  if (text.trim() === '') return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

const fraction = (value: number | null): boolean => value !== null && value >= 0 && value <= 1;

/** The boundaries the chat import takes, or null while any entry is incomplete. */
export function wizardBoundaries(entries: readonly EndEntry[]): Boundary[] | null {
  const out: Boundary[] = [];
  for (const entry of entries) {
    const pressure = number(entry.pressureBar);
    const temperature = number(entry.temperatureC);
    const gas = number(entry.gasFraction);
    const water = number(entry.waterFraction);
    if (entry.kind === '' || pressure === null || pressure <= 0 || temperature === null) return null;
    if (!fraction(gas) || !fraction(water)) return null;
    out.push({
      node: entry.node, kind: entry.kind, pressure_pa: Number((pressure * 1e5).toPrecision(12)),
      temperature_c: temperature, gas_fraction: gas as number, water_fraction: water as number,
    });
  }
  return out;
}

export interface WizardRequestInput {
  readonly path: string;
  readonly tab: string;
  readonly endTimeS: number;
  readonly thermal: 'adiabatic' | 'ask';
  readonly boundaries: readonly Boundary[] | null;
}

type Translate = (key: string, params?: Record<string, string | number>) => string;

/** The chat request the wizard drafts; the assistant builds the draft and the approval card saves it. */
export function wizardRequest(t: Translate, input: WizardRequestInput): string {
  return t('pipeWizard.saveRequest', {
    path: input.path,
    tab: input.tab,
    endTime: input.endTimeS,
    thermal: t(input.thermal === 'adiabatic' ? 'pipeWizard.thermalAdiabaticText' : 'pipeWizard.thermalAskText'),
    boundaries: JSON.stringify(input.boundaries ?? []),
  });
}
