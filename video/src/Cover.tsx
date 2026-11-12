import React from 'react';
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { MONO, UI } from './fonts';

/**
 * README cover: 2560x1280, 60 fps, 5 s, looping.
 *
 * Frame 0 already shows the whole cover, so the reduced-motion poster is the
 * first frame and the loop seam lands on the same state. Only small regions
 * move (title sheen, step highlight, cursor), which keeps the GIF small.
 *
 * The image layers are real screenshots of the running app (assets/screens);
 * blur, grain and glow are composition layers on top of them.
 */

export const COVER_FPS = 60;
export const COVER_FRAMES = 300;
export const COVER_WIDTH = 2560;
export const COVER_HEIGHT = 1280;

const INK = '#16161e';
const LINE = '#3b4261';
const BLUE = '#7aa2f7';
const GREEN = '#9ece6a';
const TEXT = '#f7f9fa';
const MUTED = '#c0caf5';
const RADIUS = 56;
const STEP_FRAMES = 60;
const STEPS = ['Ask', 'Check', 'Approve', 'Run', 'Results'];

const Mark: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" shapeRendering="crispEdges">
    <rect width="16" height="16" fill={INK} />
    <path d="M0 0H16V16H0ZM1 1V15H15V1Z" fill={LINE} fillRule="evenodd" />
    <path d="M2 4H4V5H5V6H6V7H7V9H6V10H5V11H4V12H2V11H3V10H4V9H5V7H4V6H3V5H2Z" fill={BLUE} />
    <rect x="8" y="10" width="3" height="2" fill={BLUE} />
    <rect x="12" y="4" width="2" height="8" fill={GREEN} />
  </svg>
);

const Grain: React.FC = () => (
  <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity: 0.07, mixBlendMode: 'overlay' }}>
    <filter id="cover-grain">
      <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="7" stitchTiles="stitch" />
      <feColorMatrix type="saturate" values="0" />
    </filter>
    <rect width="100%" height="100%" filter="url(#cover-grain)" />
  </svg>
);

/** Weight of step i at this frame: 1 when lit, 0 when off, eased in between; wraps 4 -> 0 at the loop seam. */
const stepWeight = (frame: number, i: number) => {
  const ease = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic) } as const;
  const start = i * STEP_FRAMES;
  const on = interpolate(frame, [start - 8, start], [0, 1], ease);
  const off = interpolate(frame, [start + STEP_FRAMES - 8, start + STEP_FRAMES], [1, 0], ease);
  const lit = Math.min(on, off);
  if (i === 0) return Math.max(lit, interpolate(frame, [COVER_FRAMES - 8, COVER_FRAMES], [0, 1], ease));
  return lit;
};

const Shot: React.FC<{ src: string; x: number; y: number; w: number; h: number; position: string; dim?: number }> = ({
  src, x, y, w, h, position, dim = 0,
}) => (
  <div
    style={{
      position: 'absolute', left: x, top: y, width: w, height: h, borderRadius: 22, overflow: 'hidden',
      border: `2px solid ${LINE}`, boxShadow: '0 40px 90px rgba(0,0,0,0.55), 0 0 0 1px rgba(122,162,247,0.10)',
      backgroundColor: INK,
    }}
  >
    <Img src={staticFile(src)} style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: position }} />
    {dim > 0 && <AbsoluteFill style={{ backgroundColor: `rgba(22,22,30,${dim})` }} />}
  </div>
);

export const Cover: React.FC<{ outside?: string }> = ({ outside = 'transparent' }) => {
  const frame = useCurrentFrame();
  const sheen = interpolate(frame, [0, 46], [-30, 130], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic),
  });
  const cursorOn = frame % 60 < 36;

  return (
    <AbsoluteFill style={{ backgroundColor: outside }}>
      <AbsoluteFill style={{ borderRadius: RADIUS, overflow: 'hidden', backgroundColor: INK }}>
        <AbsoluteFill>
          <Img
            src={staticFile('cover/02-workspace.png')}
            style={{ width: '100%', height: '100%', objectFit: 'cover', filter: 'blur(34px) brightness(0.42) saturate(1.15)', transform: 'scale(1.08)' }}
          />
        </AbsoluteFill>
        <AbsoluteFill
          style={{
            background: `radial-gradient(1200px 700px at 22% 26%, rgba(122,162,247,0.24), transparent 70%),
                         radial-gradient(1000px 640px at 88% 92%, rgba(120,90,220,0.22), transparent 72%),
                         linear-gradient(90deg, rgba(22,22,30,0.94) 0%, rgba(22,22,30,0.86) 44%, rgba(22,22,30,0.30) 100%)`,
          }}
        />
        <Grain />

        <Shot src="cover/01-chat.png" x={1600} y={120} w={840} h={560} position="100% 45%" dim={0.25} />
        <Shot src="cover/03-results.png" x={1330} y={470} w={1000} h={650} position="40% 20%" />

        <div style={{ position: 'absolute', left: 150, top: 230, width: 1180 }}>
          <Mark size={128} />
          <div style={{ position: 'relative', marginTop: 46, display: 'flex', alignItems: 'center' }}>
            <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: 124, letterSpacing: -3, color: TEXT, lineHeight: 1 }}>
              OLGA Companion
            </div>
            <div style={{ width: 34, height: 104, marginLeft: 22, backgroundColor: GREEN, opacity: cursorOn ? 1 : 0 }} />
            <div
              style={{
                position: 'absolute', inset: '-20px -40px', pointerEvents: 'none',
                background: `linear-gradient(105deg, transparent ${sheen - 12}%, rgba(255,255,255,0.22) ${sheen}%, transparent ${sheen + 12}%)`,
                mixBlendMode: 'screen',
              }}
            />
          </div>
          <div style={{ fontFamily: UI, fontWeight: 500, fontSize: 46, lineHeight: 1.42, color: MUTED, marginTop: 48 }}>
            Plan, check and run OLGA pipeline cases from a chat.
            <br />
            Every file write and every run waits for your approval.
          </div>
          <div style={{ display: 'flex', gap: 18, marginTop: 64 }}>
            {STEPS.map((label, i) => {
              const w = stepWeight(frame, i);
              return (
                <div
                  key={label}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 14, padding: '16px 24px',
                    border: `2px solid ${w > 0.5 ? BLUE : LINE}`,
                    backgroundColor: `rgba(122,162,247,${0.9 * w})`,
                    color: w > 0.5 ? INK : MUTED,
                    fontFamily: MONO, fontSize: 30,
                  }}
                >
                  <span style={{ fontWeight: 700 }}>{i + 1}</span>
                  <span>{label}</span>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
