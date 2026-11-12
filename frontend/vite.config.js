import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000
  },
  // `npm run preview` only: makes /separate-test.html cross-origin isolated so WebAssembly threads work (Nginx does this on the server)
  preview: { headers: { 'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp' } },
  build: {
    // extra pages, not linked from the app: /device-test.html (render on the user's device), /separate-test.html (remove speech on the user's device)
    rollupOptions: { input: { main: 'index.html', deviceTest: 'device-test.html', separateTest: 'separate-test.html' } },
  },
})
