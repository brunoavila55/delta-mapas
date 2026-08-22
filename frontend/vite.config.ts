import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    restoreMocks: true,
  },
  build: {
    // MapLibre is isolated in the lazy properties route (~249 kB gzip).
    chunkSizeWarningLimit: 1000,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://backend:8000', changeOrigin: false },
    },
    watch: {
      // Bind mounts from the Windows host into the Docker container don't
      // propagate inotify events, so chokidar needs to poll for changes.
      usePolling: true,
      interval: 300,
    },
  },
})
