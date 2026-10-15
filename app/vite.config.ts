import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Tauri expects a fixed dev port and no auto-open. In a plain browser the
// UI talks to `tetclipper serve`, proxied here so dev stays same-origin.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1430,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/files': 'http://127.0.0.1:8765'
    }
  },
  build: {
    target: 'es2022'
  }
})
