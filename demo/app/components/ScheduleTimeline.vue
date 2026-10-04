<script setup lang="ts">
// One row per system: when each appliance cycle runs over the day (96 quarter-hours).
import type { Appliance, RunResult } from '~/composables/useDemoData'

const props = defineProps<{ appliances: Appliance[], results: RunResult[], selected: string }>()
const emit = defineEmits<{ select: [key: string] }>()

const color = (i: number) => APPLIANCE_COLORS[i % APPLIANCE_COLORS.length]
const left = (slot: number) => `${(slot / SLOTS) * 100}%`
const width = (slots: number) => `${(slots / SLOTS) * 100}%`
const keyOf = (r: RunResult) => `${r.system}|${r.model}`
const hours = Array.from({ length: 9 }, (_, i) => i * 3)
</script>

<template>
  <div class="space-y-1.5">
    <!-- hour axis -->
    <div class="grid grid-cols-[11rem_1fr] gap-3 text-[10px] text-dimmed">
      <span />
      <div class="relative h-4">
        <span v-for="h in hours" :key="h" class="absolute -translate-x-1/2" :style="{ left: left(h * 4) }">{{ String(h).padStart(2, '0') }}</span>
      </div>
    </div>

    <!-- user windows -->
    <div class="grid grid-cols-[11rem_1fr] gap-3 items-center">
      <span class="text-xs text-muted">Allowed windows</span>
      <div class="relative rounded bg-elevated/40" :style="{ height: `${appliances.length * 6 + 4}px` }">
        <div
          v-for="(a, i) in appliances"
          :key="a.id"
          class="absolute h-1 rounded-full opacity-60"
          :style="{ left: left(a.earliest), width: width(a.deadline - a.earliest), top: `${2 + i * 6}px`, background: color(i) }" />
      </div>
    </div>

    <!-- one row per system -->
    <button
      v-for="r in results"
      :key="keyOf(r)"
      class="grid grid-cols-[11rem_1fr] gap-3 items-center w-full text-left rounded-md px-1 -mx-1 py-0.5 transition"
      :class="selected === keyOf(r) ? 'bg-primary/10 ring-1 ring-primary/40' : 'hover:bg-elevated/60'"
      @click="emit('select', keyOf(r))">
      <span class="text-xs truncate" :class="selected === keyOf(r) ? 'text-highlighted font-medium' : 'text-muted'">
        {{ r.label }}<span v-if="MODEL_LABELS[r.model]" class="text-dimmed"> · {{ MODEL_LABELS[r.model] }}</span>
        <UIcon v-if="!r.feasible" name="i-lucide-triangle-alert" class="size-3 text-error align-[-1px]" />
      </span>
      <div class="relative h-6 rounded bg-elevated/40">
        <template v-for="(a, i) in appliances" :key="a.id">
          <UTooltip
            v-if="r.starts[a.id] != null"
            :text="`${applianceName(a.id, a.kind)} ${slotTime(r.starts[a.id]!)}–${slotTime(Math.min(SLOTS, r.starts[a.id]! + a.profileKw.length))}`">
            <div
              class="absolute rounded-sm opacity-90"
              :style="{ left: left(r.starts[a.id]!), width: width(a.profileKw.length), top: `${3 + (i % 3) * 6}px`, height: '6px', background: color(i) }" />
          </UTooltip>
        </template>
      </div>
    </button>

    <!-- legend -->
    <div class="flex flex-wrap gap-3 pt-2 pl-[11.75rem] text-xs text-muted">
      <span v-for="(a, i) in appliances" :key="a.id" class="inline-flex items-center gap-1.5">
        <span class="inline-block size-2.5 rounded-sm" :style="{ background: color(i) }" />
        {{ applianceName(a.id, a.kind) }}
      </span>
    </div>
  </div>
</template>
