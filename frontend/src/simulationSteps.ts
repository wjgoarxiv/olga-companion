import type { I18nKey } from './i18n/ko.ts';

export type SimulationStep = {
  readonly id: 'create' | 'edit' | 'validate' | 'run' | 'analyze';
  readonly titleKey: I18nKey;
  readonly descriptionKey: I18nKey;
  readonly checkKey: I18nKey;
  readonly promptKey: I18nKey;
  readonly requiresCase: boolean;
};

export const SIMULATION_STEPS: readonly SimulationStep[] = [
  {
    id: 'create', requiresCase: false,
    titleKey: 'sim.step.create.title',
    descriptionKey: 'sim.step.create.description',
    checkKey: 'sim.step.create.check',
    promptKey: 'sim.step.create.prompt',
  },
  {
    id: 'edit', requiresCase: true,
    titleKey: 'sim.step.edit.title',
    descriptionKey: 'sim.step.edit.description',
    checkKey: 'sim.step.edit.check',
    promptKey: 'sim.step.edit.prompt',
  },
  {
    id: 'validate', requiresCase: true,
    titleKey: 'sim.step.validate.title',
    descriptionKey: 'sim.step.validate.description',
    checkKey: 'sim.step.validate.check',
    promptKey: 'sim.step.validate.prompt',
  },
  {
    id: 'run', requiresCase: true,
    titleKey: 'sim.step.run.title',
    descriptionKey: 'sim.step.run.description',
    checkKey: 'sim.step.run.check',
    promptKey: 'sim.step.run.prompt',
  },
  {
    id: 'analyze', requiresCase: true,
    titleKey: 'sim.step.analyze.title',
    descriptionKey: 'sim.step.analyze.description',
    checkKey: 'sim.step.analyze.check',
    promptKey: 'sim.step.analyze.prompt',
  },
];
