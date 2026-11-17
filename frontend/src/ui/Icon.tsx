import type { CSSProperties, ReactElement, ReactNode } from 'react';
import {
  BadgeCheck,
  Briefcase,
  ChartLine,
  Check,
  ChevronRight,
  ChevronsDown,
  Download,
  Droplets,
  File,
  Folder,
  GitBranch,
  GripVertical,
  MessageSquare,
  Moon,
  Pencil,
  Play,
  Plus,
  Minus,
  Search,
  Send,
  SeparatorVertical,
  Settings,
  Sun,
  TriangleAlert,
  X,
  type LucideIcon,
} from 'lucide-react';

/** Smooth vector symbol set: the same 34 names the pixel set had, so every
    existing usage keeps working. Generic symbols reuse lucide-react
    (strokeWidth ~1.75, currentColor, round caps); OLGA-specific symbols with
    no good lucide match are small 24x24 stroke drawings in this file.
    Decorative by default (aria-hidden); pass `label` for a standalone icon. */
export type IconName =
  | 'case' | 'edit' | 'validate' | 'run' | 'results' | 'chat' | 'settings'
  | 'fluid' | 'warning' | 'ok' | 'folder' | 'file' | 'graph' | 'export'
  | 'collapse' | 'grip' | 'chevron' | 'close' | 'send' | 'node' | 'search'
  | 'sun' | 'moon' | 'mark' | 'pipe' | 'source' | 'sink' | 'valve' | 'riser' | 'separator'
  | 'plus' | 'minus' | 'bar' | 'cross';

type CustomProps = {
  readonly size?: number | string;
  readonly className?: string;
  readonly style?: CSSProperties;
  readonly role?: 'img';
  readonly 'aria-label'?: string;
  readonly 'aria-hidden'?: boolean | 'true' | 'false';
  readonly focusable?: boolean | 'true' | 'false' | 'auto';
  readonly x?: number | string;
  readonly y?: number | string;
};

type AnyIcon = LucideIcon | ((props: CustomProps) => ReactElement);

function custom(children: ReactNode): (props: CustomProps) => ReactElement {
  return function CustomIcon({ size = 24, className, ...rest }: CustomProps) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        className={className}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
        {...rest}
      >
        {children}
      </svg>
    );
  };
}

const STROKE_PROPS = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const;

const NodeIcon = custom(
  <g {...STROKE_PROPS}>
    <circle cx="12" cy="12" r="2.5" />
    <path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4" />
  </g>,
);

const MarkIcon = custom(
  <g {...STROKE_PROPS}>
    <path d="M5 6l5 6-5 6" />
    <path d="M13 18h6" />
  </g>,
);

const PipeIcon = custom(
  <g {...STROKE_PROPS}>
    <path d="M2.5 9h19" />
    <path d="M2.5 15h19" />
    <path d="M7 9v6" />
    <path d="M17 9v6" />
  </g>,
);

const SourceIcon = custom(
  <g {...STROKE_PROPS}>
    <path d="M2.5 12H13" />
    <path d="M10 7.5 14.5 12 10 16.5" />
    <circle cx="18" cy="12" r="2.5" />
  </g>,
);

const SinkIcon = custom(
  <g {...STROKE_PROPS}>
    <circle cx="6" cy="12" r="2.5" />
    <path d="M11 12h10.5" />
    <path d="M17.5 7.5 22 12l-4.5 4.5" />
  </g>,
);

const ValveIcon = custom(
  <g {...STROKE_PROPS}>
    <path d="M4 7.5 12 12l-8 4.5z" />
    <path d="M20 7.5 12 12l8 4.5z" />
    <path d="M12 12V4.5" />
    <path d="M9 4.5h6" />
  </g>,
);

const RiserIcon = custom(
  <g {...STROKE_PROPS}>
    <path d="M5 21v-9a5 5 0 0 1 5-5h9" />
    <path d="M16 4l3 3-3 3" />
    <path d="M2.5 21h7" />
  </g>,
);

const SeparatorIcon = custom(
  <g {...STROKE_PROPS}>
    <rect x="3" y="9" width="18" height="7" rx="3.5" />
    <path d="M8 9V5" />
    <path d="M16 16v3.5" />
  </g>,
);

const MAP: Record<IconName, AnyIcon> = {
  case: Briefcase,
  edit: Pencil,
  validate: BadgeCheck,
  run: Play,
  results: ChartLine,
  chat: MessageSquare,
  settings: Settings,
  fluid: Droplets,
  warning: TriangleAlert,
  ok: Check,
  folder: Folder,
  file: File,
  graph: GitBranch,
  export: Download,
  collapse: ChevronsDown,
  grip: GripVertical,
  chevron: ChevronRight,
  close: X,
  send: Send,
  node: NodeIcon,
  search: Search,
  sun: Sun,
  moon: Moon,
  mark: MarkIcon,
  pipe: PipeIcon,
  source: SourceIcon,
  sink: SinkIcon,
  valve: ValveIcon,
  riser: RiserIcon,
  separator: SeparatorIcon,
  plus: Plus,
  minus: Minus,
  bar: SeparatorVertical,
  cross: X,
};

export function Icon({
  name,
  size = 18,
  label,
  className,
}: {
  readonly name: IconName;
  readonly size?: number;
  readonly label?: string;
  readonly className?: string;
}) {
  const C = MAP[name];
  const cls = ['ui-icon', className].filter(Boolean).join(' ');
  const px = { '--px': size } as CSSProperties;
  if (label === undefined) {
    return <C size={size} className={cls} style={px} aria-hidden="true" focusable="false" />;
  }
  return <C size={size} className={cls} style={px} role="img" aria-label={label} focusable="false" />;
}

/** The same symbol drawn inside an SVG (topology nodes): a nested viewport
    positioned at x/y, so it scales like any other node glyph. */
export function IconInSvg({ name, x, y, size, className }: {
  readonly name: IconName;
  readonly x: number;
  readonly y: number;
  readonly size: number;
  readonly className?: string;
}) {
  const C = MAP[name];
  return <C size={size} x={x} y={y} className={className} aria-hidden="true" focusable="false" />;
}
