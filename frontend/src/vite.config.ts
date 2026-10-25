import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Only the React UI is served by Vite. All backend URLs remain owned by FastAPI.
const backend = process.env.AEAI_BACKEND_URL || 'http://127.0.0.1:8000';
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      ['/runs', '/auth', '/data-sources', '/connectors', '/investigations', '/admin', '/health', '/metrics', '/run-inspector'].map(path => [path, { target: backend, changeOrigin: true }]),
    ),
  },
});
