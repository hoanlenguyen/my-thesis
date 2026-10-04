<script setup lang="ts">
// Total household load (base load + scheduled cycles) of one recommendation, with the peak limit.
import { Line } from '@unovis/ts'
import { VisXYContainer, VisLine, VisArea, VisAxis, VisTooltip, VisPlotline } from '@unovis/vue'
import type { Appliance } from '~/composables/useDemoData'

const props = defineProps<{ baseLoadKw: number[], appliances: Appliance[], starts: Record<string, number>, peakLimitKw: number }>()
type P = { slot: number, base: number, total: number }

const data = computed<P[]>(() => {
  const total = [...props.baseLoadKw]
  for (const a of props.appliances) {
    const s = props.starts[a.id]
    if (s == null) continue
    a.profileKw.forEach((p, i) => { if (s + i < total.length) total[s + i] = (total[s + i] ?? 0) + p })
  }
  return total.map((t, slot) => ({ slot, base: props.baseLoadKw[slot] ?? 0, total: t }))
})
const overload = computed(() => data.value.some(d => d.total > props.peakLimitKw + 1e-6))
const x = (d: P) => d.slot
const ticks = Array.from({ length: 13 }, (_, i) => i * 8)
const yMax = computed(() => Math.max(props.peakLimitKw * 1.15, ...data.value.map(d => d.total)))
const triggers = {
  [Line.selectors.line]: (d: P) => `<span style="white-space:nowrap">${slotTime(d.slot)} · total <b>${d.total.toFixed(2)}</b> kW (base ${d.base.toFixed(2)})</span>`
}
</script>

<template>
  <div>
    <VisXYContainer :data="data" :x="x" :y-domain="[0, yMax]" :padding="{ top: 12, bottom: 4 }" class="h-40 w-full">
      <VisArea :x="x" :y="(d: P) => d.base" color="var(--ui-text-dimmed)" :opacity="0.18" />
      <VisLine :x="x" :y="(d: P) => d.total" :color="overload ? 'var(--ui-error)' : 'var(--ui-primary)'" :line-width="2" />
      <VisPlotline :value="peakLimitKw" axis="y" color="var(--ui-error)" :line-width="1" line-style="longDash" :label-text="`Peak limit ${peakLimitKw} kW`" />
      <VisAxis type="x" :tick-values="ticks" :tick-format="(s: number) => slotTime(s)" />
      <VisAxis type="y" :num-ticks="4" :tick-format="(v: number) => `${v}`" />
      <VisTooltip :triggers="triggers" />
    </VisXYContainer>
    <p class="mt-1 text-xs" :class="overload ? 'text-error' : 'text-dimmed'">
      <span class="inline-block w-3 h-2 align-middle mr-1 rounded-sm bg-[var(--ui-text-dimmed)] opacity-30" />base load
      <span class="inline-block w-3 border-t-2 align-middle mx-1" :class="overload ? 'border-error' : 'border-primary'" />total load
      <span v-if="overload" class="ml-2 font-medium">· exceeds the peak limit</span>
    </p>
  </div>
</template>

<style scoped>
.unovis-xy-container {
  --vis-axis-grid-color: var(--ui-border);
  --vis-axis-tick-color: var(--ui-border);
  --vis-axis-tick-label-color: var(--ui-text-dimmed);
  --vis-tooltip-background-color: var(--ui-bg);
  --vis-tooltip-border-color: var(--ui-border);
  --vis-tooltip-text-color: var(--ui-text-highlighted);
}
</style>
