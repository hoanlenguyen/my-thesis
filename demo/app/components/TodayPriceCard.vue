<script setup lang="ts">
// Today's Nord Pool FI price by hour, fetched live from Sähkötin (allows browser requests) and
// converted to what a household pays with the same tariff as the thesis. Not part of the recorded results.
interface SahkotinResponse { prices: { date: string, value: number }[] }

const TZ = 'Europe/Helsinki'
const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
const hourFmt = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', hour12: false })
const today = dayFmt.format(new Date())
const nowHour = Number(hourFmt.format(new Date())) % 24

const from = new Date(Date.now() - 36 * 3600_000).toISOString()
const to = new Date(Date.now() + 36 * 3600_000).toISOString()
const { data, status, refresh } = useFetch<SahkotinResponse>('https://sahkotin.fi/prices', {
  query: { start: from, end: to },
  key: 'sahkotin-today',
  server: false
})

// Average per Helsinki hour of today (the API may return quarter-hours or hours).
const hours = computed<number[] | null>(() => {
  const buckets: number[][] = Array.from({ length: 24 }, () => [])
  for (const p of data.value?.prices ?? []) {
    const t = new Date(p.date)
    if (dayFmt.format(t) !== today) continue
    buckets[Number(hourFmt.format(t)) % 24]!.push(consumerCents(p.value))
  }
  if (buckets.some(b => !b.length)) return null
  return buckets.map(b => b.reduce((a, v) => a + v, 0) / b.length)
})

// Cheapest three consecutive hours still ahead today: a simple tip, like Hiilivahti's next low window.
const bestWindow = computed(() => {
  const h = hours.value
  if (!h) return null
  let best: { start: number, avg: number } | null = null
  for (let s = nowHour; s + 3 <= 24; s++) {
    const avg = (h[s]! + h[s + 1]! + h[s + 2]!) / 3
    if (!best || avg < best.avg) best = { start: s, avg }
  }
  return best
})
</script>

<template>
  <UCard>
    <template #header>
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-zap" class="size-4 text-primary" />
          <span class="font-semibold text-sm text-highlighted">Today's electricity price in Finland, by hour</span>
          <UBadge color="info" variant="subtle" size="xs">Live</UBadge>
        </div>
        <UButton icon="i-lucide-refresh-cw" size="xs" variant="ghost" color="neutral" :loading="status === 'pending'" aria-label="Refresh" @click="() => refresh()" />
      </div>
    </template>

    <div v-if="hours">
      <PriceBars :prices="hours" :now-hour="nowHour" />
      <p v-if="bestWindow" class="mt-3 text-sm text-highlighted">
        <UIcon name="i-lucide-lightbulb" class="size-4 text-warning align-[-3px]" />
        Cheapest three hours still ahead today: <b>{{ String(bestWindow.start).padStart(2, '0') }}:00–{{ String(bestWindow.start + 3).padStart(2, '0') }}:00</b>
        at {{ bestWindow.avg.toFixed(2) }} c/kWh on average.
      </p>
    </div>
    <div v-else-if="status === 'pending' || status === 'idle'" class="h-40 rounded-lg bg-elevated/40 animate-pulse" />
    <p v-else class="text-sm text-muted">Today's prices are not available right now. Please try again later.</p>

    <p class="mt-3 text-xs text-dimmed">
      {{ today }} · Nord Pool FI day-ahead price via Sähkötin, as paid by a household: spot price plus 0.5 c retail margin,
      5.0 c transfer fee and 2.25 c electricity tax, with 25.5 % VAT (the tariff used in the thesis).
    </p>
  </UCard>
</template>
