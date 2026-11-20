# Network — corporate proxy toggle

Some enterprise PCs drop outbound provider connections every few minutes. The
app has a settings toggle that routes provider requests through a local proxy
the administrator approved, and re-runs a small connection check before every
save so the toggle never turns on against a dead port.

## How to turn it on

1. Open **Settings → Network**.
2. Enter the proxy **host** (usually `127.0.0.1`), **port**, and the
   provider you want the probe to reach (`api.openai.com`, `api.x.ai`,
   `api.anthropic.com`, etc.).
3. Click **Test connection now**. The app sends one HTTP `CONNECT` through
   the proxy and reports the outcome:
   - *OK · 12 ms* — the proxy accepted the tunnel.
   - *Connection refused* — the port is not open.
   - *The proxy returned 502* — the proxy answered but the upstream call did
     not complete. Fix the upstream route; a 502 is **not** a certificate
     error, so trusting more roots will not help.
   - *Timed out waiting for the proxy* — the proxy accepted the socket but
     never answered. Usually a mismatched port.
4. If the probe is OK, tick **Route provider requests through the proxy**
   and press **Save**. The status bar shows a small **Proxy on** badge
   while the toggle is on.

## When to use it

- Only when provider responses stop mid-stream on this PC.
- When your administrator has given you a local proxy address that is
  allowed to reach provider hosts.

## When not to use it

- On a personal PC with no corporate proxy — leaving it off is faster.
- If the error is `401 Unauthorized` or `403 Forbidden`: that is a sign-in
  problem, not a network one.

## What the app sends

The probe is one HTTP `CONNECT` with no credentials and no body. It runs
when you press **Test connection now**, when you save, and when the sidecar
starts if the toggle was left on. No proxy credentials are stored.

The saved values live in `~/.olga_copilot/proxy.json` with user-only
permissions, next to the other sign-in records.
