import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend runs on :8000 and serves /api. Proxying here means the browser
// makes same-origin requests (no CORS) and the API base is simply "/api".
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
