<script setup lang="ts">
import type { ScenarioIndex } from '~/composables/useDemoData'

const { data: benchmarks } = await useBenchmarks()
const benchId = useState('bench', () => 'q2')
// One filter per factor of the benchmark design (null = all)
const filters = reactive<Record<FactorKey, string | null>>({ pattern: null, load: null, limit: null })

const bench = computed(() => benchmarks.value?.find(b => b.id === benchId.value) ?? benchmarks.value?.[0])
const days = computed(() =>
  (bench.value?.scenarios ?? []).filter((d: ScenarioIndex) =>
    (Object.keys(filters) as FactorKey[]).every(k => !filters[k] || d[k] === filters[k]))
)
const factorKeys = Object.keys(FACTORS) as FactorKey[]
</script>

<template>
  <div class="space-y-5">
    <div>
      <h1 class="text-2xl font-semibold text-highlighted">Daily recommendations</h1>
      <p class="mt-1 text-sm text-muted">
        Pick a household-day to compare what every system recommends and what it would cost. Each day combines a
        price pattern, a household load and a peak limit.
      </p>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <button
        v-for="b in benchmarks"
        :key="b.id"
        class="px-3 py-1.5 rounded-lg text-xs font-medium border transition-all"
        :class="bench?.id === b.id ? 'bg-primary border-primary text-white' : 'bg-elevated border-default text-muted hover:text-highlighted'"
        @click="benchId = b.id">
        {{ b.label }}
      </button>
    </div>

    <div class="space-y-2">
      <div v-for="k in factorKeys" :key="k" class="flex flex-wrap items-center gap-1.5">
        <span class="text-xs text-muted w-28 shrink-0">{{ FACTORS[k].label }}</span>
        <UButton size="xs" :variant="filters[k] === null ? 'soft' : 'ghost'" color="neutral" @click="filters[k] = null">
          All
        </UButton>
        <UButton
          v-for="(label, v) in FACTORS[k].values"
          :key="v"
          size="xs"
          color="neutral"
          :variant="filters[k] === v ? 'soft' : 'ghost'"
          @click="filters[k] = v">
          {{ label }}
        </UButton>
      </div>
      <p class="text-xs text-dimmed">{{ days.length }} of {{ bench?.scenarios.length ?? 0 }} household-days</p>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <NuxtLink v-for="d in days" :key="d.id" :to="`/days/${bench?.id}/${d.id}`">
        <UCard class="hover:ring-primary/50 transition">
          <div class="flex items-start justify-between gap-2">
            <div>
              <p class="font-semibold text-highlighted">{{ d.id }}</p>
              <p class="text-xs text-muted">
                {{ d.date }} · {{ d.appliances }} appliances · limit {{ d.peakLimitKw }} kW
                <UTooltip v-if="raisedLimitNote(d)" :text="raisedLimitNote(d)!" :content="{ side: 'top' }">
                  <UBadge color="warning" variant="subtle" size="xs" class="ml-0.5 cursor-help">raised</UBadge>
                </UTooltip>
              </p>
            </div>
          </div>
          <p class="mt-2 text-xs text-dimmed">{{ scenarioTypeLabel(d.type) }}</p>
          <div class="mt-3 flex items-center justify-between text-sm">
            <span class="text-muted">No scheduling {{ euro(d.naiveCost) }}</span>
            <UTooltip v-if="smallSavingNote(d)" :text="smallSavingNote(d)!.text" :content="{ side: 'top' }">
              <UBadge color="neutral" variant="subtle" size="sm" class="cursor-help" icon="i-lucide-info">
                {{ smallSavingNote(d)!.label }}
              </UBadge>
            </UTooltip>
            <span v-else class="font-medium text-success">save up to {{ euro(d.achievableSaving) }}</span>
          </div>
        </UCard>
      </NuxtLink>
    </div>
  </div>
</template>
