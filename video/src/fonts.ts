import { continueRender, delayRender, staticFile } from 'remotion';

/**
 * The video must be set in the same faces as the application, or the README
 * reads as a different product from the thing it is advertising.
 *
 * Pretendard is the app's own self-hosted file (frontend/public/fonts); the
 * Meslo face for the video is the full Nerd Font TTF kept in assets/fonts (the
 * app itself now ships the Meslo LGS NF woff2 pair). Both are copied by
 * `npm run fonts`. Rendering is held with delayRender until they are
 * actually loaded: without that, the first frames are laid out in the fallback
 * face and the type visibly jumps a few frames in.
 */

export const UI = '"Pretendard Variable", Pretendard, sans-serif';
export const MONO = '"MesloLGS Nerd Font Mono", "Cascadia Mono", monospace';

const handle = delayRender('Loading OLGA Companion brand faces');

const style = document.createElement('style');
style.textContent = `
@font-face {
  font-family: "Pretendard Variable";
  font-weight: 100 900;
  font-style: normal;
  src: url("${staticFile('fonts/PretendardVariable.woff2')}") format("woff2-variations");
}
@font-face {
  font-family: "MesloLGS Nerd Font Mono";
  font-weight: 400;
  font-style: normal;
  src: url("${staticFile('fonts/MesloLGSNerdFontMono-Regular.ttf')}") format("truetype");
}
@font-face {
  font-family: "MesloLGS Nerd Font Mono";
  font-weight: 700;
  font-style: normal;
  src: url("${staticFile('fonts/MesloLGSNF-Bold.woff2')}") format("woff2");
}
`;
document.head.appendChild(style);

Promise.all([
  document.fonts.load('700 92px "MesloLGS Nerd Font Mono"'),
  document.fonts.load('400 27px "MesloLGS Nerd Font Mono"'),
  document.fonts.load('500 31px "Pretendard Variable"'),
  document.fonts.load('700 17px "Pretendard Variable"'),
  document.fonts.load('700 124px "MesloLGS Nerd Font Mono"'),
])
  .then(() => continueRender(handle))
  // Never hang the render on a font: fallbacks are ugly, a stuck render is worse.
  .catch(() => continueRender(handle));
