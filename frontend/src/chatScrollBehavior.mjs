// Chat autoscroll glides only when neither the OS (prefers-reduced-motion) nor the app's own
// motion setting (data-motion="off" on <html>, set by appearance.ts) asks for less motion.
export function chatScrollBehavior({ systemReduced, motionAttr }) {
  return systemReduced || motionAttr === 'off' ? 'auto' : 'smooth';
}
