// Static demo: replays recorded benchmark results from public/data (see tools/export_demo_data.py).
// Theme and components are adapted from the Low-carbon-alerts (Hiilivahti) app.
export default defineNuxtConfig({
  modules: ['@nuxt/ui', '@vueuse/nuxt'],
  ssr: false,
  devtools: { enabled: false },
  css: ['~/assets/css/main.css'],
  app: {
    head: { title: 'HEMS agent demo' }
  },
  // The "Try it" page calls the local Python API (uv run --extra demo uvicorn hems.demo_api:app --port 8001).
  // In development /api is proxied to it; set NUXT_PUBLIC_API_BASE to call it from a static build.
  runtimeConfig: {
    public: { apiBase: '' }
  },
  nitro: {
    devProxy: { '/api': { target: 'http://localhost:8001/api', changeOrigin: true } }
  },
  compatibilityDate: '2024-07-11'
})
