export type ProxyStatusSnapshot = { readonly enabled: boolean; readonly ok: boolean };

export function getProxyStatus(): ProxyStatusSnapshot;
export function subscribe(listener: (snapshot: ProxyStatusSnapshot) => void): () => void;
export function refresh(): Promise<ProxyStatusSnapshot>;
