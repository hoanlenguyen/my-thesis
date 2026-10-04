<script setup lang="ts">
import type { SystemSummary } from '~/composables/useDemoData'

const { data: benchmarks } = await useBenchmarks()
const benchId = useState('bench', () => 'main')
const showLocal = ref(false)

const bench = computed(() => benchmarks.value?.find(b => b.id === benchId.value))
const rows = computed<SystemSummary[]>(() =>
  (bench.value?.summary ?? [])
    .filter(r => r.system !== 'naive' && r.system !== 'milp')
    .filter(r => showLocal.value || r.model !== 'gpt-oss-20b')
    .sort((a, b) => (b.savingsCaptured ?? -1) - (a.savingsCaptured ?? -1))
)
const hasLocal = computed(() => bench.value?.summary.some(r => r.model === 'gpt-oss-20b'))
const days = computed(() => bench.value?.scenarios.length ?? 0)
const totals = computed(() => {
  const s = bench.value?.scenarios ?? []
  return { naive: s.reduce((a, d) => a + d.naiveCost, 0), milp: s.reduce((a, d) => a + d.milpCost, 0) }
})

const barWidth = (v: number | null) => `${Math.max(0, Math.min(100, (v ?? 0) * 100))}%`
const barColor = (r: SystemSummary) => {
  const g = SYSTEM_GROUPS[r.system]
  return g === 'agent' ? 'bg-primary' : g === 'tool' ? 'bg-info' : g === 'rule' ? 'bg-warning' : 'bg-error'
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold text-highlighted">
        Which system actually reduces the electricity bill?
      </h1>
      <p class="mt-1 text-sm text-muted max-w-3xl">
        Every day, each system receives the household's appliance plan (which cycles to run, when each is
        ready and must be finished), its base load, its 3.5 kW peak limit and the day's prices, and recommends a start
        time for each appliance. Each recommendation is scored by what the household would pay.
      </p>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <button
        v-for="b in benchmarks"
        :key="b.id"
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all"
        :class="benchId === b.id ? 'bg-primary border-primary text-white' : 'bg-elevated border-default text-muted hover:text-highlighted'"
        @click="benchId = b.id">
        {{ b.label }}
      </button>
      <USwitch v-if="hasLocal" v-model="showLocal" label="Show local model (runs in progress)" size="sm" class="ml-2" />
    </div>

    <div class="grid gap-3 sm:grid-cols-3">
      <UCard>
        <p class="text-xs text-muted">Household-days</p>
        <p class="text-2xl font-bold text-highlighted tabular-nums">{{ days }}</p>
      </UCard>
      <UCard>
        <p class="text-xs text-muted">Cost with no scheduling (all days)</p>
        <p class="text-2xl font-bold text-highlighted tabular-nums">{{ euro(totals.naive) }}</p>
      </UCard>
      <UCard>
        <p class="text-xs text-muted">Lowest possible cost (MILP optimum)</p>
        <p class="text-2xl font-bold text-success tabular-nums">{{ euro(totals.milp) }}</p>
        <p class="text-xs text-dimmed">Achievable saving {{ euro(totals.naive - totals.milp) }}</p>
      </UCard>
    </div>

    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-piggy-bank" class="size-4 text-primary" />
          <span class="font-semibold text-sm text-highlighted">Share of the achievable saving each system captures</span>
        </div>
      </template>
      <div class="space-y-3">
        <div v-for="r in rows" :key="r.system + r.model" class="grid grid-cols-[minmax(0,14rem)_1fr_auto] items-center gap-3">
          <div class="min-w-0">
            <p class="text-sm font-medium text-highlighted truncate">{{ r.label }}</p>
            <div class="flex items-center gap-1.5">
              <UBadge :color="groupBadge(r.system).color" variant="subtle" size="xs">
                {{ groupBadge(r.system).label }}
              </UBadge>
              <span v-if="MODEL_LABELS[r.model]" class="text-[11px] text-dimmed">{{ MODEL_LABELS[r.model] }}</span>
            </div>
          </div>
          <div class="h-3 rounded-full bg-elevated overflow-hidden">
            <div class="h-full rounded-full" :class="barColor(r)" :style="{ width: barWidth(r.savingsCaptured) }" />
          </div>
          <span class="text-sm font-semibold tabular-nums w-14 text-right">{{ pct((r.savingsCaptured ?? 0) * 100, 0) }}</span>
        </div>
      </div>
      <p class="mt-4 text-xs text-dimmed">
        Saving captured = (cost with no scheduling − system's cost) ÷ (cost with no scheduling − optimal cost), pooled over
        all runs. A schedule that breaks the peak limit or a time window is counted at the no-scheduling cost.
      </p>
    </UCard>

    <UCard :ui="{ body: 'p-0 sm:p-0' }">
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-table" class="size-4 text-primary" />
          <span class="font-semibold text-sm text-highlighted">Details</span>
        </div>
      </template>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="text-xs text-muted border-b border-default">
            <tr>
              <th class="text-left font-medium px-4 py-2">System</th>
              <th class="text-right font-medium px-4 py-2">Valid schedules</th>
              <th class="text-right font-medium px-4 py-2">Above optimum</th>
              <th class="text-right font-medium px-4 py-2">Time per day</th>
              <th class="text-right font-medium px-4 py-2">API cost per day</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.system + r.model" class="border-b border-default last:border-0">
              <td class="px-4 py-2 text-highlighted">
                {{ r.label }} <span v-if="MODEL_LABELS[r.model]" class="text-dimmed text-xs">· {{ MODEL_LABELS[r.model] }}</span>
              </td>
              <td class="px-4 py-2 text-right tabular-nums">
                {{ r.feasible }}/{{ r.runs }}
                <UIcon v-if="r.feasible < r.runs" name="i-lucide-triangle-alert" class="size-3.5 text-warning align-[-2px]" />
              </td>
              <td class="px-4 py-2 text-right tabular-nums">{{ pct(r.gapMean, 2) }}</td>
              <td class="px-4 py-2 text-right tabular-nums">{{ r.latencyMean == null ? '–' : `${r.latencyMean.toFixed(r.latencyMean < 1 ? 2 : 1)} s` }}</td>
              <td class="px-4 py-2 text-right tabular-nums">{{ r.usdPerRun ? `$${r.usdPerRun.toFixed(4)}` : '–' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </UCard>

    <div class="flex justify-end">
      <UButton to="/days" icon="i-lucide-arrow-right" trailing>
        See the daily recommendations
      </UButton>
    </div>
  </div>
</template>
