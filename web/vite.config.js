import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'prompt',
      manifest: {
        name: 'MBTA Commuter Rail',
        short_name: 'CR',
        description: 'Live MBTA Commuter Rail — positions, delays, and predicted platforms',
        theme_color: '#80276C',
        background_color: '#0f1115',
        display: 'standalone',
        start_url: '/',
        icons: [],
      },
    }),
  ],
})
