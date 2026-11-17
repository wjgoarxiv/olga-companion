const remembered: string[] = [];

/** Figure paths already exported in this page session. */
export function rememberSessionFigures(paths: readonly string[]): void {
  for (const path of paths) {
    if (path.trim() && !remembered.includes(path)) remembered.push(path);
  }
}

export function sessionFigures(): readonly string[] {
  return remembered.slice();
}
