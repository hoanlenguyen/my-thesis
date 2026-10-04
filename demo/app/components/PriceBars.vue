<script setup lang="ts">
// Hourly electricity price as 24 bars: the four cheapest hours green, the four most expensive red.
// Colour bands follow Low-carbon-alerts' clean -> dirty convention (success / warning / error).
const props = withDefaults(defineProps<{ prices: number[], nowHour?: number | null, unit?: string }>(), {
  nowHour: null,
  unit: 'c/kWh'
})
const sorted = computed(() => [...props.prices].sort((a, b) => a - b))
const cheapCut = computed(() => sorted.value[3] ?? Infinity)
const dearCut = computed(() => sorted.value[sorted.value.length - 4] ?? -Infinity)
const max = computed(() => Math.max(...props.prices, 1))
const min = computed(() => Math.min(...props.prices, 0))
const band = (p: number) => (p <= cheapCut.value ? 'bg-success' : p >= dearCut.value ? 'bg-error' : 'bg-warning/70')
const height = (p: number) => `${Math.max(3, ((p - Math.min(0, min.value)) / (max.value - Math.min(0, min.value))) * 100)}%`
const cheapest = computed(() => props.prices.indexOf(sorted.value[0] ?? 0))
const dearest = computed(() => props.prices.indexOf(sorted.value[sorted.value.length - 1] ?? 0))
</script>

<template>
  <div>
    <div class="flex items-end gap-0.5 h-36">
      <UTooltip v-for="(p, h) in prices" :key="h" :text="`${String(h).padStart(2, '0')}:00–${String(h + 1).padStart(2, '0')}:00 · ${p.toFixed(2)} ${unit}`">
        <div class="relative flex-1 h-full flex items-end">
          <div class="w-full rounded-t-sm transition-all" :class="[band(p), nowHour === h ? 'ring-2 ring-info ring-offset-1 ring-offset-default' : '']" :style="{ height: height(p) }" />
        </div>
      </UTooltip>
    </div>
    <div class="flex gap-0.5 text-[9px] text-dimmed mt-1">
      <span v-for="h in 24" :key="h" class="flex-1 text-center">{{ (h - 1) % 3 === 0 ? String(h - 1).padStart(2, '0') : '' }}</span>
    </div>
    <div class="mt-2 flex flex-wrap gap-2 text-xs">
      <UBadge color="success" variant="subtle" size="sm" icon="i-lucide-trending-down">
        Cheapest {{ String(cheapest).padStart(2, '0') }}:00 · {{ (prices[cheapest] ?? 0).toFixed(2) }} {{ unit }}
      </UBadge>
      <UBadge color="error" variant="subtle" size="sm" icon="i-lucide-trending-up">
        Most expensive {{ String(dearest).padStart(2, '0') }}:00 · {{ (prices[dearest] ?? 0).toFixed(2) }} {{ unit }}
      </UBadge>
      <UBadge v-if="nowHour != null" color="info" variant="subtle" size="sm" icon="i-lucide-clock">
        Now {{ String(nowHour).padStart(2, '0') }}:00 · {{ (prices[nowHour] ?? 0).toFixed(2) }} {{ unit }}
      </UBadge>
    </div>
  </div>
</template>
