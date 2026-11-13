export type FlowpathView = 'plan' | 'elevation' | 'side' | 'isometric';

export type FlowpathPoint =
  | { x: number; y: number; z: number }
  | { x_m: number; y_m: number; z_m: number };

export interface FlowpathSection {
  section_index: number;
  pipe_section_index: number;
  pipe_label: string;
  length_m: number;
  diameter_m: number;
  chainage_start_m: number;
  chainage_end_m: number;
  start: FlowpathPoint;
  center: FlowpathPoint;
  end: FlowpathPoint;
}

export interface ProjectedPoint { x: number; y: number }

export interface ProjectedSection extends Omit<FlowpathSection, 'start' | 'center' | 'end'> {
  start: ProjectedPoint;
  center: ProjectedPoint;
  end: ProjectedPoint;
}

export interface FlowpathProjection {
  view: FlowpathView;
  viewBox: string;
  bounds: { minX: number; maxX: number; minY: number; maxY: number };
  segments: ProjectedSection[];
}

export function buildFlowpathProjection(
  sections: FlowpathSection[],
  options: {
    view: FlowpathView;
    width: number;
    height: number;
    padding: number;
    elevationExaggeration: number;
  },
): FlowpathProjection;

export function transitionSectionSelection(
  key: string,
  currentIndex: number | null,
  sectionCount: number,
): { handled: boolean; nextIndex: number | null };

export function defaultFlowpathView(sections: FlowpathSection[]): FlowpathView;
