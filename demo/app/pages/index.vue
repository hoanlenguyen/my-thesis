<script setup lang="ts">
import type { SystemSummary } from '~/composables/useDemoData'

const { data: benchmarks } = await useBenchmarks()
const benchId = useState('bench', () => 'q2')
const showIterations = ref(false)

const bench = computed(() => benchmarks.value?.find(b => b.id === benchId.value) ?? benchmarks.value?.[0])
const rows = computed<SystemSummary[]>(() =>
  (bench.value?.summary ?? [])
    .filter(r => r.system !== 'naive' && r.system !== 'milp')
    .filter(r => showIterations.value || SYSTEM_GROUPS[r.system] !== 'iteration')
    .sort((a, b) => (b.savingPct ?? -1) - (a.savingPct ?? -1))
)
const hasIterations = computed(() => bench.value?.summary.some(r => SYSTEM_GROUPS[r.system] === 'iteration'))
const days = computed(() => bench.value?.scenarios.length ?? 0)
const totals = computed(() => {
  const s = bench.value?.scenarios ?? []
  return { naive: s.reduce((a, d) => a + d.naiveCost, 0), milp: s.reduce((a, d) => a + d.milpCost, 0) }
})
// Saving of the optimum, the upper bound of every bar
const optimumPct = computed(() => totals.value.naive ? (1 - totals.value.milp / totals.value.naive) * 100 : 0)

const barWidth = (v: number | null) => `${Math.max(0, Math.min(100, ((v ?? 0) / (optimumPct.value || 1)) * 100))}%`
const barColor = (r: SystemSummary) => {
  const g = SYSTEM_GROUPS[r.system]
  return g === 'agent' ? 'bg-primary' : g === 'iteration' ? 'bg-primary/50' : g === 'tool' ? 'bg-info' : g === 'rule' ? 'bg-warning' : g === 'heuristic' ? 'bg-slate-500' : 'bg-error'
}

// SQ1 targets for an LLM recommendation (thesis H1c): mean latency and API cost per recommendation
const TARGET_LATENCY_S = 60
const TARGET_USD = 0.1
const isLlm = (r: SystemSummary) => r.model !== '-'

// SQ2: saving by condition, one column per system shown above (same order)
const factorKeys = Object.keys(FACTORS) as FactorKey[]
const levelOrder = (k: FactorKey, level: string) => Object.keys(FACTORS[k].values).indexOf(level)
const conditionsOf = (k: FactorKey) =>
  (bench.value?.byCondition ?? []).filter(c => c.factor === k).sort((a, b) => levelOrder(k, a.level) - levelOrder(k, b.level))
const levelLabel = (k: FactorKey, level: string) => (FACTORS[k].values as Record<string, string>)[level] ?? level
const cell = (row: { systems: Record<string, { savingPct: number | null, validShare: number | null }> }, r: SystemSummary) =>
  row.systems[`${r.system}|${r.model}`]
// Shade by the share of the optimal saving reached in that condition
const cellStyle = (saving: number | null | undefined, optimum: number | null) => {
  if (saving == null || !optimum || optimum <= 0) return {}
  const share = Math.max(0, Math.min(1, saving / optimum))
  return { backgroundColor: `color-mix(in oklab, var(--ui-success) ${Math.round(share * 35)}%, transparent)` }
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
        ready and must be finished), its base load, its peak limit (3.5 or 8 kW, higher on days whose base load alone exceeds it) and the day's prices, and recommends
        a start time for each appliance. Each recommendation is scored by what the household would pay.
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
      <USwitch v-if="hasIterations" v-model="showIterations" label="Show earlier design iterations" size="sm" class="ml-2" />
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
          <span class="font-semibold text-sm text-highlighted">Saving compared with no scheduling</span>
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
            <div class="h-full rounded-full" :class="barColor(r)" :style="{ width: barWidth(r.savingPct) }" />
          </div>
          <span class="text-sm font-semibold tabular-nums w-16 text-right">{{ pct(r.savingPct, 1) }}</span>
        </div>
        <div class="grid grid-cols-[minmax(0,14rem)_1fr_auto] items-center gap-3 pt-2 border-t border-default">
          <p class="text-sm text-muted">Optimum (upper bound)</p>
          <div class="h-3 rounded-full bg-elevated overflow-hidden">
            <div class="h-full w-full rounded-full bg-success/40" />
          </div>
          <span class="text-sm font-semibold tabular-nums w-16 text-right text-success">{{ pct(optimumPct, 1) }}</span>
        </div>
      </div>
      <p class="mt-4 text-xs text-dimmed">
        Saving = (cost with no scheduling − system's cost) ÷ cost with no scheduling, pooled over all runs; a full bar
        reaches the optimum. A schedule that breaks the peak limit or a time window is counted at the no-scheduling cost.
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
              <th class="text-right font-medium px-4 py-2">Share of optimal saving</th>
              <th class="text-right font-medium px-4 py-2">Above optimum</th>
              <th class="text-right font-medium px-4 py-2">
                Time per day<br><span class="font-normal text-dimmed">LLM target &lt; {{ TARGET_LATENCY_S }} s</span>
              </th>
              <th class="text-right font-medium px-4 py-2">
                API cost per day<br><span class="font-normal text-dimmed">LLM target &lt; ${{ TARGET_USD.toFixed(2) }}</span>
              </th>
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
              <td class="px-4 py-2 text-right tabular-nums">{{ pct((r.savingsCaptured ?? 0) * 100, 0) }}</td>
              <td class="px-4 py-2 text-right tabular-nums">{{ pct(r.gapMean, 2) }}</td>
              <td class="px-4 py-2 text-right tabular-nums" :class="isLlm(r) && (r.latencyMean ?? 0) >= TARGET_LATENCY_S ? 'text-warning font-medium' : ''">
                {{ r.latencyMean == null ? '–' : `${r.latencyMean.toFixed(r.latencyMean < 1 ? 2 : 1)} s` }}
                <template v-if="isLlm(r) && r.latencyMean != null">
                  <UIcon v-if="r.latencyMean >= TARGET_LATENCY_S" name="i-lucide-triangle-alert" class="size-3.5 align-[-2px]" />
                  <UIcon v-else name="i-lucide-circle-check" class="size-3.5 text-success align-[-2px]" />
                </template>
              </td>
              <td class="px-4 py-2 text-right tabular-nums">
                {{ r.usdPerRun ? `$${r.usdPerRun.toFixed(4)}` : '–' }}
                <template v-if="isLlm(r) && r.usdPerRun != null">
                  <UIcon v-if="r.usdPerRun >= TARGET_USD" name="i-lucide-triangle-alert" class="size-3.5 text-warning align-[-2px]" />
                  <UIcon v-else name="i-lucide-circle-check" class="size-3.5 text-success align-[-2px]" />
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="px-4 py-3 text-xs text-dimmed border-t border-default">
        The thesis sets two practical targets for an LLM recommendation: a mean response time below {{ TARGET_LATENCY_S }} s and an
        API cost below ${{ TARGET_USD.toFixed(2) }} per recommendation. A warning sign marks a missed target.
      </p>
    </UCard>

    <UCard :ui="{ body: 'p-0 sm:p-0' }">
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-grid-3x3" class="size-4 text-primary" />
          <span class="font-semibold text-sm text-highlighted">Saving by condition: when does each system work?</span>
        </div>
      </template>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="text-xs text-muted border-b border-default">
            <tr>
              <th class="text-left font-medium px-3 py-2">Condition</th>
              <th class="text-right font-medium px-3 py-2 text-success">Optimum</th>
              <th v-for="r in rows" :key="r.system + r.model" class="text-right font-medium px-3 py-2 min-w-20">
                {{ r.label }}
              </th>
            </tr>
          </thead>
          <tbody>
            <template v-for="k in factorKeys" :key="k">
              <tr class="bg-elevated/50">
                <td :colspan="rows.length + 2" class="px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
                  {{ FACTORS[k].label }}
                </td>
              </tr>
              <tr v-for="c in conditionsOf(k)" :key="k + c.level" class="border-b border-default last:border-0">
                <td class="px-3 py-1.5 text-highlighted whitespace-nowrap">
                  {{ levelLabel(k, c.level) }} <span class="text-dimmed text-xs">· {{ c.scenarios }} days</span>
                </td>
                <td class="px-3 py-1.5 text-right tabular-nums font-medium text-success">{{ pct(c.optimumPct, 1) }}</td>
                <td
                  v-for="r in rows"
                  :key="r.system + r.model"
                  class="px-3 py-1.5 text-right tabular-nums"
                  :style="cellStyle(cell(c, r)?.savingPct, c.optimumPct)"
                  :title="cell(c, r)?.validShare != null ? `${Math.round((cell(c, r)!.validShare ?? 0) * 100)} % valid schedules` : ''">
                  {{ pct(cell(c, r)?.savingPct, 1) }}
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <p class="px-4 py-3 text-xs text-dimmed border-t border-default">
        Saving compared with no scheduling, pooled over all runs of the days with that condition; each factor is averaged
        over the other two. The greener a cell, the closer the system comes to the optimum. Hover a cell for the share of
        valid schedules.
      </p>
    </UCard>

    <div class="flex justify-end">
      <UButton to="/days" icon="i-lucide-arrow-right" trailing>
        See the daily recommendations
      </UButton>
    </div>
  </div>
</template>
