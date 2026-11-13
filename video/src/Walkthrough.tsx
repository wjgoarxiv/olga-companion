import React from 'react';
import { AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { MONO, UI } from './fonts';

/**
 * README walkthrough.
 *
 * Every product frame is a real screenshot of the running application, captured
 * by scratchpad/capture.mjs against a sanitized demo workspace. Nothing here
 * redraws or simulates the UI -- the motion is a slow push-in over the actual
 * capture, so what a viewer sees is what the app renders.
 */

export const FPS = 30;
export const WIDTH = 1440;
export const HEIGHT = 1000;
export const TITLE_FRAMES = 72;
export const OUTRO_FRAMES = 60;

const INK = '#16161e'; // Tokyo Night canvas, as the app and icon tile
const TEAL = '#7aa2f7'; // the app's signal-blue accent (name kept; used for kicker and link)
const FADE = 14; // crossfade length, in frames

export const SCENES = [
  {
    src: '01-chat.png',
    frames: 96,
    kicker: 'Chat',
    caption: 'Ask about a case in plain language. The assistant reads and proposes — it never acts alone.',
    focus: [0.5, 0.45] as const,
  },
  {
    src: '02-workspace.png',
    frames: 108,
    kicker: 'Workspace',
    caption: 'Topology resolved straight from the .genkey — nodes, flowpaths, and geometry on one canvas.',
    focus: [0.62, 0.58] as const,
  },
  {
    src: '03-results.png',
    frames: 126,
    kicker: 'Results',
    caption: 'Overlay variables from a .tpl, convert units, and read a summary that describes without judging.',
    focus: [0.68, 0.5] as const,
  },
  {
    src: '04-run.png',
    frames: 96,
    kicker: 'Run',
    caption: 'The exact OLGA command is shown first. Nothing executes until you approve it.',
    focus: [0.5, 0.45] as const,
  },
  {
    src: '05-settings.png',
    frames: 108,
    kicker: 'Updates',
    caption: 'Signed release channel. Downloads can be automatic; installing is always your click.',
    focus: [0.42, 0.62] as const,
  },
];

// The app's own faces, loaded by ./fonts. Anything else makes the video read as
// a different product from the one it is showing.
const mono = MONO;
const sans = UI;

/**
 * The product mark: the Terminalcore `>_` prompt glyph and block cursor on the
 * app-icon tile, kept in step with assets/logo/mark-tile.svg (16-unit integer
 * grid, crispEdges, square corners). Inlined rather than loaded via staticFile
 * so it needs no extra asset. Use sizes that are multiples of 16 so every grid
 * step lands on whole pixels.
 */
const Mark: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" shapeRendering="crispEdges">
    <rect width="16" height="16" fill="#16161e" />
    <path d="M0 0H16V16H0ZM1 1V15H15V1Z" fill="#3b4261" fillRule="evenodd" />
    <path
      d="M2 4H4V5H5V6H6V7H7V9H6V10H5V11H4V12H2V11H3V10H4V9H5V7H4V6H3V5H2Z"
      fill="#7aa2f7"
    />
    <rect x="8" y="10" width="3" height="2" fill="#7aa2f7" />
    <rect x="12" y="4" width="2" height="8" fill="#9ece6a" />
  </svg>
);

/** Soft radial blooms, matching the cover art. */
const Backdrop: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: INK }}>
    <AbsoluteFill
      style={{
        background: `radial-gradient(1100px 620px at 62% 18%, rgba(122,162,247,0.26), transparent 68%),
                     radial-gradient(900px 560px at 20% 86%, rgba(70,60,170,0.22), transparent 70%)`,
      }}
    />
  </AbsoluteFill>
);

const Title: React.FC = () => {
  const frame = useCurrentFrame();
  const rise = interpolate(frame, [0, 24], [18, 0], { extrapolateRight: 'clamp' });
  const fadeIn = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: 'clamp' });
  const fadeOut = interpolate(frame, [TITLE_FRAMES - FADE, TITLE_FRAMES], [1, 0], {
    extrapolateLeft: 'clamp',
  });

  return (
    <AbsoluteFill style={{ opacity: Math.min(fadeIn, fadeOut) }}>
      <Backdrop />
      <AbsoluteFill
        style={{
          justifyContent: 'center',
          alignItems: 'center',
          transform: `translateY(${rise}px)`,
        }}
      >
        <Mark size={96} />
        <div style={{ fontFamily: mono, fontSize: 92, fontWeight: 700, color: '#f7f9fa', letterSpacing: -2, marginTop: 26 }}>
          olga-companion
        </div>
        <div style={{ fontFamily: mono, fontSize: 27, color: '#9aa5ad', marginTop: 22 }}>
          Supervise OLGA runs with evidence you can check.
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Scene: React.FC<{ scene: (typeof SCENES)[number]; motion: boolean }> = ({ scene, motion }) => {
  const frame = useCurrentFrame();
  const { frames, focus } = scene;

  const fadeIn = interpolate(frame, [0, FADE], [0, 1], { extrapolateRight: 'clamp' });
  const fadeOut = interpolate(frame, [frames - FADE, frames], [1, 0], { extrapolateLeft: 'clamp' });
  // Slow push-in toward the region the caption is talking about.
  //
  // Disabled for the GIF build: a continuous zoom changes every pixel of every
  // frame, which defeats interframe GIF compression entirely (16 MB vs ~2 MB
  // for the same content held still). The MP4 keeps the motion.
  const scale = motion ? interpolate(frame, [0, frames], [1.02, 1.09]) : 1.04;
  const captionIn = motion
    ? interpolate(frame, [8, 26], [0, 1], { extrapolateRight: 'clamp' })
    : 1;

  return (
    <AbsoluteFill style={{ opacity: Math.min(fadeIn, fadeOut) }}>
      <Backdrop />
      <AbsoluteFill style={{ overflow: 'hidden' }}>
        <Img
          src={staticFile(scene.src)}
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            objectPosition: `${focus[0] * 100}% ${focus[1] * 100}%`,
            transform: `scale(${scale})`,
          }}
        />
      </AbsoluteFill>

      {/* Legibility scrim: the app is a light UI, the caption bar is dark. */}
      <AbsoluteFill
        style={{
          background: 'linear-gradient(to bottom, transparent 58%, rgba(8,10,13,0.94) 88%)',
        }}
      />

      <AbsoluteFill
        style={{
          justifyContent: 'flex-end',
          padding: '0 76px 62px',
          opacity: captionIn,
          transform: `translateY(${motion ? interpolate(frame, [8, 26], [14, 0], { extrapolateRight: 'clamp' }) : 0}px)`,
        }}
      >
        <div
          style={{
            fontFamily: mono,
            fontSize: 17,
            letterSpacing: 3.4,
            textTransform: 'uppercase',
            color: TEAL,
            marginBottom: 14,
          }}
        >
          {scene.kicker}
        </div>
        <div style={{ fontFamily: sans, fontSize: 31, lineHeight: 1.36, color: '#f3f6f8', maxWidth: 1120 }}>
          {scene.caption}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const fadeIn = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill style={{ opacity: fadeIn }}>
      <Backdrop />
      <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center' }}>
        <Mark size={64} />
        <div style={{ fontFamily: mono, fontSize: 58, fontWeight: 700, color: '#f7f9fa', marginTop: 22 }}>
          olga-companion
        </div>
        <div style={{ fontFamily: mono, fontSize: 25, color: TEAL, marginTop: 20 }}>
          github.com/wjgoarxiv/olga-companion
        </div>
        <div style={{ fontFamily: sans, fontSize: 20, color: '#8b959c', marginTop: 30 }}>
          Windows · Apache-2.0
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const Walkthrough: React.FC<{ motion?: boolean }> = ({ motion = true }) => {
  let cursor = TITLE_FRAMES;

  return (
    <AbsoluteFill style={{ backgroundColor: INK }}>
      <Sequence durationInFrames={TITLE_FRAMES}>
        <Title />
      </Sequence>

      {SCENES.map((scene) => {
        // Overlap each scene into the previous one so the crossfade has
        // something to fade against instead of flashing the backdrop.
        const from = cursor - FADE;
        cursor += scene.frames - FADE;
        return (
          <Sequence key={scene.src} from={from} durationInFrames={scene.frames}>
            <Scene scene={scene} motion={motion} />
          </Sequence>
        );
      })}

      <Sequence from={cursor - FADE} durationInFrames={OUTRO_FRAMES}>
        <Outro />
      </Sequence>
    </AbsoluteFill>
  );
};
