import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The admin dashboard is its own app (own build, own sub-domain, e.g. admin.example.com). Dev server: http://localhost:3001
export default defineConfig({
  plugins: [react()],
  server: { port: 3001, strictPort: true },
})
