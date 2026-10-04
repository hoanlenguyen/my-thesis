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
  compatibilityDate: '2024-07-11'
})
