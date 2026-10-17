<script setup lang="ts">
// Consumer price per 15-minute slot, styled like Low-carbon-alerts' CarbonChart (Unovis).
import { VisXYContainer, VisLine, VisArea, VisAxis, VisTooltip, VisCrosshair } from '@unovis/vue'

const props = defineProps<{ prices: number[] }>()
type P = { slot: number, v: number }
const data = computed<P[]>(() => props.prices.map((v, slot) => ({ slot, v })))
const x = (d: P) => d.slot
const y = (d: P) => d.v
const ticks = Array.from({ length: 13 }, (_, i) => i * 8)
// Tooltip of the slot nearest the pointer (a trigger on the line itself would get the whole series, not one point)
const tip = (d?: P) => d ? `<span style="white-space:nowrap">${slotTime(d.slot)} · <b>${d.v.toFixed(2)}</b> c/kWh</span>` : ''
</script>

<template>
  <VisXYContainer :data="data" :x="x" :y="y" :padding="{ top: 12, bottom: 4 }" class="h-44 w-full">
    <VisArea :x="x" :y="y" color="var(--ui-primary)" :opacity="0.12" />
    <VisLine :x="x" :y="y" color="var(--ui-primary)" :line-width="2" />
    <VisAxis type="x" :tick-values="ticks" :tick-format="(s: number) => slotTime(s)" />
    <VisAxis type="y" :num-ticks="4" :tick-format="(v: number) => `${v}`" />
    <VisCrosshair :x="x" :y="[y]" :template="tip" color="var(--ui-primary)" />
    <VisTooltip />
  </VisXYContainer>
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
