export function isPackagedLocation(location: { readonly hostname: string; readonly protocol: string }): boolean;
export function obtainSessionToken(sources: {
  readonly packaged: boolean;
  readonly native: () => Promise<unknown>;
  readonly http: () => Promise<string>;
}): Promise<string>;
