import { Composition } from 'remotion';
import { Walkthrough, SCENES, FPS, WIDTH, HEIGHT, TITLE_FRAMES, OUTRO_FRAMES } from './Walkthrough';
import { Cover, COVER_FPS, COVER_FRAMES, COVER_WIDTH, COVER_HEIGHT } from './Cover';

const totalFrames =
  TITLE_FRAMES + SCENES.reduce((sum, scene) => sum + scene.frames, 0) + OUTRO_FRAMES;

export const RemotionRoot: React.FC = () => (
  <>
    {/* Motion build -> assets/demo.mp4 */}
    <Composition
      id="Walkthrough"
      component={Walkthrough}
      durationInFrames={totalFrames}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      defaultProps={{ motion: true }}
    />
    {/* Still-hold build -> assets/demo.gif. Same real captures, no continuous
        zoom, so GIF interframe compression actually works. */}
    <Composition
      id="WalkthroughGif"
      component={Walkthrough}
      durationInFrames={totalFrames}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      defaultProps={{ motion: false }}
    />
    {/* README cover -> assets/cover.mp4 (outside painted), cover-poster.png and cover.gif (outside transparent) */}
    <Composition
      id="Cover"
      component={Cover}
      durationInFrames={COVER_FRAMES}
      fps={COVER_FPS}
      width={COVER_WIDTH}
      height={COVER_HEIGHT}
      defaultProps={{ outside: 'transparent' }}
    />
  </>
);
