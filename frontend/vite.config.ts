import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Dev server proxies /api to the FastAPI backend so the browser sees a single
// origin (no CORS). Change the target if the backend runs elsewhere.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: {
      // Override the backend location with VITE_API_TARGET when needed.
      '/api': { target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    // Split vendor chunks so the initial bundle stays small.
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
          table: ['@tanstack/react-table'],
        },
      },
    },
  },
});
