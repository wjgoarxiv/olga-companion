import { useSyncExternalStore } from 'react';
import {
  DEFAULT_SIGNIFICANT_FIGURES,
  loadSignificantFigures,
  saveSignificantFigures,
  type SignificantFigures,
} from './significantFigures.mjs';

type Listener = () => void;

let current = loadSignificantFigures();
const listeners = new Set<Listener>();

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): SignificantFigures {
  return current;
}

export function setSignificantFigures(significantFigures: SignificantFigures): void {
  if (significantFigures === current) return;
  current = significantFigures;
  saveSignificantFigures(significantFigures);
  for (const listener of listeners) listener();
}

export function useSignificantFigures(): SignificantFigures {
  return useSyncExternalStore(subscribe, snapshot, () => DEFAULT_SIGNIFICANT_FIGURES);
}
