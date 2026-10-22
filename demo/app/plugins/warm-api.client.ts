// Wakes the cloud API and EMHASS as soon as the site loads. Both scale to zero and need up to a minute to start;
// a visitor reading the replay pages first then finds them running on the Try-it page. Once per browser tab.
export default defineNuxtPlugin(() => {
  const base = useRuntimeConfig().public.apiBase as string
  if (!base) return // local development: the API runs all the time
  try {
    if (sessionStorage.getItem('hems-warm')) return
    sessionStorage.setItem('hems-warm', '1')
  } catch {
    /* storage blocked: warm anyway */
  }
  fetch(`${base}/api/warm`).catch(() => {
    /* a failed wake-up only means the first recommendation waits */
  })
})
