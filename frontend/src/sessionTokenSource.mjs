/** Where the window gets the backend's session token (0.1.20 review). In the packaged app the
    shell holds it (read from the backend's stdout) and the HTTP route is closed, so another
    local program cannot fetch it and approve cards. The dev page still uses the route. */

export function isPackagedLocation(location) {
  return location.hostname === 'tauri.localhost' || location.protocol === 'tauri:';
}

export async function obtainSessionToken({ packaged, native, http }) {
  if (!packaged) return http();
  const token = await native();
  if (typeof token !== 'string' || !token) throw new Error('session_token_unavailable');
  return token;
}
