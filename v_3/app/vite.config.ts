import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // La app (tauri.conf.json devUrl) se conecta a 5173. Si ese puerto está ocupado (un Vite viejo que
  // quedó vivo), fallar en lugar de usar otro: si no, la app sigue recibiendo el código viejo del
  // Vite huérfano sin que nada avise (pasó el 2026-11-26).
  server: { port: 5173, strictPort: true },
})
