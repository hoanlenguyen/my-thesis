<script setup lang="ts">
// Estimated saving of each system over the household's whole recording period: its real cycles,
// ready at their recorded start and finished by midnight, priced at recent Finnish prices.
import type { FullPeriod } from '~/composables/useDemoData'

const props = defineProps<{ house: number, data: FullPeriod | null | undefined }>()
const LABELS: Record<string, string> = {
  milp: 'MILP optimum', multi: 'Multi-agent pipeline', single: 'Single agent', timer: 'Smart timer',
  emhass_rest: 'EMHASS, profiles', cheapest_hours: 'Cheapest hours (HA)', oneshot: 'LLM without tools'
}
const h = computed(() => props.data?.households.find(x => x.house === props.house))
const perYear = (v: number) => (h.value ? (v / h.value.recordedDays) * 365 : 0)
const rows = computed(() => {
  const totals = h.value?.totals ?? {}
  const best = totals.milp?.saving ?? 0
  return Object.entries(totals)
    .map(([system, t]) => ({ system, label: LABELS[system] ?? system, ...t, ofBest: best > 0 ? t.saving / best : 0 }))
    .sort((a, b) => b.saving - a.saving)
})
const barColor = (system: string) => {
  const g = SYSTEM_GROUPS[system]
  return g === 'agent' ? 'bg-primary' : g === 'tool' ? 'bg-info' : g === 'rule' ? 'bg-warning' : g === 'llm' ? 'bg-error' : 'bg-success'
}
</script>

<template>
  <UCard v-if="h">
    <template #header>
      <div class="flex items-center gap-2">
        <UIcon name="i-lucide-piggy-bank" class="size-4 text-primary" />
        <span class="font-semibold text-sm text-highlighted">Estimated saving over the whole recording period</span>
      </div>
    </template>

    <div class="grid gap-3 sm:grid-cols-4 mb-4">
      <div class="rounded-lg bg-elevated/40 px-3 py-2">
        <p class="text-[11px] text-muted">Recording period</p>
        <p class="text-sm font-semibold text-highlighted">{{ h.firstDay }} – {{ h.lastDay }}</p>
        <p class="text-[11px] text-dimmed">{{ h.recordedDays }} days</p>
      </div>
      <div class="rounded-lg bg-elevated/40 px-3 py-2">
        <p class="text-[11px] text-muted">Cycles to schedule</p>
        <p class="text-sm font-semibold text-highlighted">{{ h.cycles }} on {{ h.daysWithCycles }} days</p>
        <p v-if="h.cyclesPastMidnight" class="text-[11px] text-dimmed">{{ h.cyclesPastMidnight }} ran past midnight (kept as recorded)</p>
      </div>
      <div class="rounded-lg bg-elevated/40 px-3 py-2">
        <p class="text-[11px] text-muted">Cost at the real start times</p>
        <p class="text-sm font-semibold text-highlighted">{{ euro(h.naiveCost) }}</p>
        <p class="text-[11px] text-dimmed">{{ euro(perYear(h.naiveCost)) }} per year</p>
      </div>
      <div class="rounded-lg bg-success/10 px-3 py-2">
        <p class="text-[11px] text-muted">Best possible saving</p>
        <p class="text-sm font-semibold text-success">{{ euro(h.totals.milp?.saving) }}</p>
        <p class="text-[11px] text-dimmed">{{ euro(perYear(h.totals.milp?.saving ?? 0)) }} per year</p>
      </div>
    </div>

    <div class="space-y-2">
      <div v-for="r in rows" :key="r.system" class="grid grid-cols-[minmax(0,12rem)_1fr_5.5rem_5.5rem_6rem] items-center gap-3 text-sm">
        <span class="truncate text-highlighted">
          {{ r.label }}
          <UBadge v-if="r.estimated" color="neutral" variant="subtle" size="xs" class="ml-1">estimated</UBadge>
        </span>
        <div class="h-2.5 rounded-full bg-elevated overflow-hidden">
          <div class="h-full rounded-full" :class="barColor(r.system)" :style="{ width: `${Math.max(0, Math.min(1, r.ofBest)) * 100}%` }" />
        </div>
        <span class="text-right tabular-nums font-semibold">{{ euro(r.saving) }}</span>
        <span class="text-right tabular-nums text-muted">{{ euro(perYear(r.saving)) }}/yr</span>
        <span class="text-right text-xs text-dimmed tabular-nums">
          {{ r.validDays == null ? `${Math.round((r.share ?? 0) * 100)} % of optimum` : `${r.validDays}/${h.daysWithCycles} valid days` }}
        </span>
      </div>
    </div>

    <p class="mt-4 text-xs text-dimmed leading-relaxed">
      Every washing-machine, dishwasher and tumble-dryer cycle the household actually ran is scheduled on its own day: ready
      at its recorded start, finished by midnight, with the household's typical base load and the 3.5 kW peak limit.
      Each day is priced at the same calendar day of {{ data?.priceYear }} (what a household pays today). No scheduling = the
      recorded start times; a plan that breaks the peak limit saves nothing that day. The LLM systems are not run on these
      days: their saving is estimated from their share of the optimum on the held-out benchmark.
    </p>
  </UCard>
  <UCard v-else>
    <p class="text-sm text-muted">The whole-period estimate for this household is not computed yet.</p>
  </UCard>
</template>
