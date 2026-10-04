<script setup lang="ts">
// 24 hour cells shaded by how often an appliance is in use in that hour, in the style of
// Low-carbon-alerts' CarbonHourStrip. `share` is the fraction of recorded days (0-1).
const props = withDefaults(defineProps<{ share: number[], compact?: boolean, labels?: boolean }>(), {
  compact: false,
  labels: false
})
const level = (s: number) => (s >= 0.5 ? 'bg-primary' : s >= 0.25 ? 'bg-primary/60' : s >= 0.1 ? 'bg-primary/30' : s >= 0.03 ? 'bg-primary/12' : 'bg-elevated/50')
const cells = computed(() => props.share.map((s, h) => ({ h, s })))
</script>

<template>
  <div>
    <div class="grid grid-cols-24 gap-px" :class="compact ? 'h-3' : 'h-6'">
      <UTooltip v-for="c in cells" :key="c.h" :text="`${String(c.h).padStart(2, '0')}:00 · in use on ${Math.round(c.s * 100)} % of days`">
        <div class="rounded-[2px] h-full" :class="level(c.s)" />
      </UTooltip>
    </div>
    <div v-if="labels" class="grid grid-cols-24 text-[9px] text-dimmed mt-0.5">
      <span v-for="h in 24" :key="h" class="text-center">{{ (h - 1) % 3 === 0 ? String(h - 1).padStart(2, '0') : '' }}</span>
    </div>
  </div>
</template>
