<script setup lang="ts">
// "When each system runs the appliances": one row per system with its appliance cycles on a 24-hour axis
// and its saving versus no scheduling. Above them, when the household usually runs these appliances
// (REFIT profile); below them, the household's appliances that no system schedules.
import type { Appliance, FixedRow, RunResult, UsualRow } from '~/composables/useDemoData'

const props = defineProps<{
  appliances: Appliance[]
  results: RunResult[]
  selected?: string
  naiveCost: number
  milpCost: number
  usual?: UsualRow[]
  fixed?: FixedRow[]
}>()
const emit = defineEmits<{ select: [key: string] }>()

const color = (i: number) => APPLIANCE_COLORS[i % APPLIANCE_COLORS.length]
const left = (slot: number) => `${(slot / SLOTS) * 100}%`
const width = (slots: number) => `${(slots / SLOTS) * 100}%`
const keyOf = (r: RunResult) => `${r.system}|${r.model}`
const hours = Array.from({ length: 9 }, (_, i) => i * 3)
const usualLevel = (s: number) => (s >= 0.25 ? 'opacity-90' : s >= 0.1 ? 'opacity-60' : s >= 0.03 ? 'opacity-30' : 'opacity-0')
const fixedLevel = (s: number) => (s >= 0.5 ? 'bg-neutral-500/70' : s >= 0.25 ? 'bg-neutral-500/45' : s >= 0.1 ? 'bg-neutral-500/25' : s >= 0.03 ? 'bg-neutral-500/12' : '')
const kindColor = (kind: string) => color(Math.max(0, props.appliances.findIndex(a => a.kind === kind)))

// Saving the household would make with this system's recommendation (invalid schedules save nothing).
const saving = (r: RunResult) => (r.feasible && r.costEur != null ? props.naiveCost - r.costEur : 0)
const achievable = computed(() => props.naiveCost - props.milpCost)
const savingClass = (r: RunResult) => {
  if (!r.feasible) return 'text-error'
  const s = saving(r)
  if (achievable.value > 1e-6 && s >= 0.9 * achievable.value) return 'text-success font-semibold'
  return s > 0.0005 ? 'text-highlighted' : 'text-muted'
}
const ROW = 'grid grid-cols-[11rem_1fr_6.5rem] gap-3 items-center'
// One lane per appliance in each system row, so no cycle is drawn over another (thinner lanes when there are many)
const laneHeight = computed(() => (props.appliances.length > 4 ? 4 : 6))
const rowHeight = computed(() => `${Math.max(24, props.appliances.length * laneHeight.value + 6)}px`)
</script>

<template>
  <div class="space-y-1.5">
    <!-- header -->
    <div :class="ROW" class="text-[10px] text-dimmed">
      <span />
      <div class="relative h-4">
        <span v-for="h in hours" :key="h" class="absolute -translate-x-1/2" :style="{ left: left(h * 4) }">{{ String(h).padStart(2, '0') }}</span>
      </div>
      <span class="text-right leading-tight">Saving vs. no scheduling</span>
    </div>

    <!-- when the household usually runs these appliances -->
    <template v-if="usual?.length">
      <div :class="ROW">
        <span class="text-[11px] font-medium text-dimmed uppercase tracking-wide">Usually used</span>
        <span class="text-[11px] text-dimmed col-span-2">when this household typically runs these appliances (REFIT, darker = more often)</span>
      </div>
      <div v-for="u in usual" :key="u.name" :class="ROW">
        <span class="text-xs text-muted truncate inline-flex items-center gap-1.5">
          <UIcon :name="applianceIcon(u.kind)" class="size-3.5 shrink-0" />{{ applianceName(u.name, u.kind) }}
        </span>
        <div class="relative h-4 rounded bg-elevated/30 grid grid-cols-24 gap-px overflow-hidden">
          <UTooltip v-for="(s, h) in u.hourly" :key="h" :text="`${String(h).padStart(2, '0')}:00 · used on ${Math.round(s * 100)} % of days`">
            <div class="h-full" :class="usualLevel(s)" :style="{ background: kindColor(u.kind) }" />
          </UTooltip>
        </div>
        <span />
      </div>
    </template>

    <!-- allowed windows of the day's cycles -->
    <div :class="ROW" class="pt-1">
      <span class="text-xs text-muted">Allowed windows</span>
      <div class="relative rounded bg-elevated/40" :style="{ height: `${appliances.length * 6 + 4}px` }">
        <template v-for="(a, i) in appliances" :key="a.id">
          <div
            v-for="([p0, p1], j) in a.periods ?? [[a.earliest, a.deadline]]"
            :key="j"
            class="absolute h-1 rounded-full opacity-60"
            :style="{ left: left(p0), width: width(p1 - p0), top: `${2 + i * 6}px`, background: color(i) }" />
        </template>
      </div>
      <span />
    </div>

    <!-- one row per system -->
    <button
      v-for="r in results"
      :key="keyOf(r)"
      :class="[ROW, selected === keyOf(r) ? 'bg-primary/10 ring-1 ring-primary/40' : 'hover:bg-elevated/60']"
      class="w-full text-left rounded-md px-1 -mx-1 py-0.5 transition"
      @click="emit('select', keyOf(r))">
      <span class="text-xs truncate" :class="selected === keyOf(r) ? 'text-highlighted font-medium' : 'text-muted'">
        {{ r.label }}<span v-if="MODEL_LABELS[r.model]" class="text-dimmed"> · {{ MODEL_LABELS[r.model] }}</span>
      </span>
      <div class="relative rounded bg-elevated/40" :style="{ height: rowHeight }">
        <template v-for="(a, i) in appliances" :key="a.id">
          <UTooltip
            v-if="r.starts[a.id] != null"
            :text="`${applianceName(a.id, a.kind)} ${slotTime(r.starts[a.id]!)}–${slotTime(Math.min(SLOTS, r.starts[a.id]! + a.profileKw.length))}`">
            <div
              class="absolute rounded-sm opacity-90"
              :style="{ left: left(r.starts[a.id]!), width: width(a.profileKw.length), top: `${3 + i * laneHeight}px`, height: `${laneHeight}px`, background: color(i) }" />
          </UTooltip>
        </template>
      </div>
      <span class="text-right text-xs tabular-nums" :class="savingClass(r)">
        <template v-if="r.system === 'naive'">–</template>
        <template v-else-if="!r.feasible">
          <UTooltip :text="r.violations[0] ?? 'Breaks a household limit'">
            <span class="inline-flex items-center gap-1"><UIcon name="i-lucide-triangle-alert" class="size-3" />invalid</span>
          </UTooltip>
        </template>
        <template v-else>
          {{ euro(saving(r), 3) }}
          <span v-if="achievable >= 0.005" class="text-dimmed font-normal">· {{ Math.round((saving(r) / achievable) * 100) }} %</span>
        </template>
      </span>
    </button>

    <!-- the household's appliances that no system schedules -->
    <template v-if="fixed?.length">
      <div :class="ROW" class="pt-3">
        <span class="text-[11px] font-medium text-dimmed uppercase tracking-wide">Not scheduled</span>
        <span class="text-[11px] text-dimmed col-span-2">the household's other appliances and their typical use; part of the base load</span>
      </div>
      <div v-for="f in fixed" :key="f.id" :class="ROW">
        <span class="text-xs text-muted truncate inline-flex items-center gap-1.5">
          <UIcon :name="applianceIcon(f.kind)" class="size-3.5 shrink-0" />
          {{ applianceName(f.id, f.kind) }}
          <UBadge v-if="f.shiftable" color="warning" variant="subtle" size="xs">partly shiftable</UBadge>
        </span>
        <div class="relative h-4 rounded bg-elevated/30 grid grid-cols-24 gap-px overflow-hidden">
          <template v-if="f.hourly">
            <UTooltip v-for="(s, h) in f.hourly" :key="h" :text="`${String(h).padStart(2, '0')}:00 · in use on ${Math.round(s * 100)} % of days`">
              <div class="h-full" :class="fixedLevel(s)" />
            </UTooltip>
          </template>
          <span v-else class="col-span-24 text-[10px] text-dimmed px-1">no usage profile</span>
        </div>
        <span class="text-right text-[11px] text-dimmed tabular-nums">{{ f.ratedKw.toFixed(2) }} kW</span>
      </div>
    </template>

    <!-- legend -->
    <div class="flex flex-wrap gap-3 pt-2 pl-[11.75rem] text-xs text-muted">
      <span v-for="(a, i) in appliances" :key="a.id" class="inline-flex items-center gap-1.5">
        <span class="inline-block size-2.5 rounded-sm" :style="{ background: color(i) }" />
        {{ applianceName(a.id, a.kind) }}
      </span>
    </div>
  </div>
</template>
