/* Plain readout formatting for coordinates and sash sizes. (This module once
   also held the label-scramble frames; Terminalcore is static, so those are gone.) */
const pad4 = (value) => String(Math.round(value)).padStart(4, '0');

export const formatCoord = (x, y) => ['X', pad4(x), '·', 'Y', pad4(y)].join(' ');

export const formatSizeLabel = (axis, px) => [axis, Math.round(px), 'PX'].join(' ');
