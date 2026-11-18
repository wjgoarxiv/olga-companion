import { createRequire } from 'node:module';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Single source of truth for the version the Updates panel reports. Keeping it
// bound to package.json avoids a second place to forget on a release bump.
const { version: appVersion } = createRequire(import.meta.url)('../package.json') as { version: string };

function assertLoopbackOrigin(value: string, name: string): string {
  const origin = new URL(value);
  const loopbackHosts = new Set(['127.0.0.1', 'localhost', '[::1]']);
  if (origin.protocol !== 'http:' || !loopbackHosts.has(origin.hostname) || origin.username || origin.password || origin.pathname !== '/') {
    throw new Error(`${name} must be an HTTP loopback origin`);
  }
  return origin.origin;
}

const sidecarOrigin = assertLoopbackOrigin(process.env.OLGA_SIDECAR_ORIGIN ?? 'http://127.0.0.1:8865', 'OLGA_SIDECAR_ORIGIN');
const proxyOrigin = process.env.OLGA_PROXY_ORIGIN ? assertLoopbackOrigin(process.env.OLGA_PROXY_ORIGIN, 'OLGA_PROXY_ORIGIN') : undefined;
const sidecarProxy = proxyOrigin
  ? { target: sidecarOrigin, headers: { Origin: proxyOrigin } }
  : sidecarOrigin;

export default defineConfig({
  root: 'frontend',
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion)
  },
  server: {
    host: '127.0.0.1',
    port: 5273,
    strictPort: true,
    // /mnt/c (DrvFS) drops inotify events under WSL, so HMR misses edits
    // without polling.
    watch: {
      usePolling: true,
      interval: 400
    },
    proxy: {
      '/api': sidecarProxy,
      '/health': sidecarProxy
    }
  },
  preview: {
    host: '127.0.0.1',
    port: 5273,
    strictPort: true
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true
  }
});
