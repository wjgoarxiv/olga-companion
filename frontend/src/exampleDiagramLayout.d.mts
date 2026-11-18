export type DiagramModel = {
  readonly nodes: readonly { readonly id: string; readonly kind: 'source' | 'sink' | 'junction' | 'closed' }[];
  readonly edges: readonly {
    readonly id: string;
    readonly from: string;
    readonly to: string;
    readonly segments: readonly { readonly id: string; readonly length_m: number; readonly rise_m: number }[];
    readonly valves: readonly { readonly pipe: string; readonly position: number; readonly scheduled: boolean }[];
  }[];
  readonly thermal: boolean;
  readonly scheduled_valves: boolean;
};
export type DiagramLayout = {
  readonly width: number;
  readonly height: number;
  readonly nodes: readonly { readonly id: string; readonly kind: string; readonly labelBelow: boolean; readonly x: number; readonly y: number }[];
  readonly paths: readonly { readonly id: string; readonly points: readonly (readonly [number, number])[]; readonly valves: readonly { readonly x: number; readonly y: number; readonly scheduled: boolean }[] }[];
  readonly ground: number | null;
};
export const DIAGRAM_WIDTH: number;
export function layoutDiagram(model: DiagramModel): DiagramLayout;
