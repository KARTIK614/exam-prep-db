import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Vite config for the exam-prep SPA.
// - React plugin for JSX/HMR/Fast Refresh.
// - `@/` alias to `src/` matches the tsconfig `paths` entry.
// - Dev proxy forwards `/api/*` to the local Rust backend on :3000, so the
//   client can use same-origin URLs and cookies work without CORS in dev.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'es2020',
    sourcemap: true,
  },
});
