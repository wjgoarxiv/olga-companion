/** Put the plot for the timestep on screen first, so "Save PNG" saves what the user sees. */
export function profilePlotFirst(exported) {
  const chosen = exported.selected_plot;
  if (!chosen || !exported.plots.includes(chosen)) return exported;
  return { ...exported, plots: [chosen, ...exported.plots.filter((plot) => plot !== chosen)] };
}
