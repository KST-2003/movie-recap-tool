import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000
  },
  build: {
    // second page: /device-test.html = proof of concept for rendering on the user's device (not linked from the app)
    rollupOptions: { input: { main: 'index.html', deviceTest: 'device-test.html' } },
  },
})
