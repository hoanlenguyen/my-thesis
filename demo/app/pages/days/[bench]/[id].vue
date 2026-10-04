<script setup lang="ts">
import type { RunResult } from '~/composables/useDemoData'

const route = useRoute()
const bench = computed(() => String(route.params.bench))
const id = computed(() => String(route.params.id))
const { data: day, status } = await useDay(bench, id)

const run = ref(1)
const showLocal = ref(false)
const keyOf = (r: RunResult) => `${r.system}|${r.model}`

// One result per system for the chosen run (deterministic systems have run 0).
const results = computed<RunResult[]>(() => {
  const all = day.value?.results ?? []
  return all.filter(r => (r.run === 0 || r.run === run.value) && (showLocal.value || r.model !== 'gpt-oss-20b'))
})
const hasLocal = computed(() => day.value?.results.some(r => r.model === 'gpt-oss-20b'))
const selected = ref('multi|gpt-4o-mini')
const current = computed(() => results.value.find(r => keyOf(r) === selected.value) ?? results.value[0])
watch(results, (rs) => { if (!rs.some(r => keyOf(r) === selected.value) && rs[0]) selected.value = keyOf(rs[0]) })
</script>

<template>
  <div v-if="day" class="space-y-5">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <UButton to="/days" icon="i-lucide-arrow-left" size="xs" variant="ghost" color="neutral" class="-ml-2 mb-1">
          All days
        </UButton>
        <h1 class="text-2xl font-semibold text-highlighted">{{ day.id }} · {{ day.date }}</h1>
        <p class="text-sm text-muted">
          Type {{ day.type }}: {{ SCENARIO_TYPES[day.type] }} · {{ day.appliances.length }} appliance cycles ·
          peak limit {{ day.peakLimitKw }} kW
        </p>
      </div>
      <div class="flex items-center gap-3">
        <div class="flex items-center gap-1">
          <span class="text-xs text-muted mr-1">LLM run</span>
          <UButton
            v-for="n in [1, 2, 3]"
            :key="n"
            size="xs"
            :variant="run === n ? 'soft' : 'ghost'"
            :color="run === n ? 'primary' : 'neutral'"
            @click="run = n">
            {{ n }}
          </UButton>
        </div>
        <USwitch v-if="hasLocal" v-model="showLocal" label="Local model" size="sm" />
      </div>
    </div>

    <div class="grid gap-3 sm:grid-cols-3">
      <UCard>
        <p class="text-xs text-muted">No scheduling</p>
        <p class="text-xl font-bold tabular-nums text-highlighted">{{ euro(day.naiveCost, 3) }}</p>
      </UCard>
      <UCard>
        <p class="text-xs text-muted">Optimal (MILP)</p>
        <p class="text-xl font-bold tabular-nums text-success">{{ euro(day.milpCost, 3) }}</p>
      </UCard>
      <UCard>
        <p class="text-xs text-muted">Achievable saving</p>
        <p class="text-xl font-bold tabular-nums text-highlighted">{{ euro(day.naiveCost - day.milpCost, 3) }}</p>
      </UCard>
    </div>

    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-receipt-euro" class="size-4 text-primary" />
          <span class="font-semibold text-sm text-highlighted">Electricity price, c/kWh incl. taxes and transfer</span>
        </div>
      </template>
      <PriceChart :prices="day.priceCents" />
    </UCard>

    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-calendar-range" class="size-4 text-primary" />
          <span class="font-semibold text-sm text-highlighted">When each system runs the appliances</span>
          <span class="text-xs text-dimmed">· click a row to see its recommendation</span>
        </div>
      </template>
      <ScheduleTimeline :appliances="day.appliances" :results="results" :selected="selected" @select="k => (selected = k)" />
    </UCard>

    <div v-if="current" class="grid gap-4 lg:grid-cols-2">
      <SystemRecommendationCard :result="current" :appliances="day.appliances" :naive-cost="day.naiveCost" :milp-cost="day.milpCost" />
      <UCard>
        <template #header>
          <div class="flex items-center gap-2">
            <UIcon name="i-lucide-activity" class="size-4 text-primary" />
            <span class="font-semibold text-sm text-highlighted">Household load with this recommendation</span>
          </div>
        </template>
        <LoadChart :base-load-kw="day.baseLoadKw" :appliances="day.appliances" :starts="current.starts" :peak-limit-kw="day.peakLimitKw" />
      </UCard>
    </div>

    <UCollapsible>
      <UButton icon="i-lucide-file-text" variant="ghost" color="neutral" size="sm" label="Show the day's appliance plan given to the systems" />
      <template #content>
        <pre class="mt-2 whitespace-pre-wrap text-xs text-muted bg-elevated/40 rounded-lg p-3">{{ day.plan }}</pre>
      </template>
    </UCollapsible>
  </div>
  <div v-else-if="status === 'pending'" class="h-64 rounded-lg bg-elevated/40 animate-pulse" />
  <div v-else class="text-sm text-muted">Day not found.</div>
</template>
