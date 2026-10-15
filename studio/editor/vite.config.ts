import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Served by the Python server at /studio (tetclipper serve). In dev, the API
// and media files are proxied to it.
export default defineConfig({
  base: '/studio/',
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/files': 'http://127.0.0.1:8765'
    }
  }
})
