<script setup lang="ts">
const { data: benchmarks } = await useBenchmarks()
const benchId = useState('bench', () => 'main')
const typeFilter = ref<string | null>(null)

const bench = computed(() => benchmarks.value?.find(b => b.id === benchId.value))
const days = computed(() =>
  (bench.value?.scenarios ?? []).filter(d => !typeFilter.value || d.type === typeFilter.value)
)
</script>

<template>
  <div class="space-y-5">
    <div>
      <h1 class="text-2xl font-semibold text-highlighted">Daily recommendations</h1>
      <p class="mt-1 text-sm text-muted">
        Pick a household-day to compare what every system recommends and what it would cost.
      </p>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <button
        v-for="b in benchmarks"
        :key="b.id"
        class="px-3 py-1.5 rounded-lg text-xs font-medium border transition-all"
        :class="benchId === b.id ? 'bg-primary border-primary text-white' : 'bg-elevated border-default text-muted hover:text-highlighted'"
        @click="benchId = b.id">
        {{ b.label }}
      </button>
    </div>

    <div class="flex flex-wrap gap-1.5">
      <UButton size="xs" :variant="typeFilter === null ? 'soft' : 'ghost'" color="neutral" @click="typeFilter = null">
        All types
      </UButton>
      <UButton
        v-for="(label, t) in SCENARIO_TYPES"
        :key="t"
        size="xs"
        color="neutral"
        :variant="typeFilter === t ? 'soft' : 'ghost'"
        @click="typeFilter = t">
        {{ t }} · {{ label }}
      </UButton>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <NuxtLink v-for="d in days" :key="d.id" :to="`/days/${benchId}/${d.id}`">
        <UCard class="hover:ring-primary/50 transition">
          <div class="flex items-start justify-between gap-2">
            <div>
              <p class="font-semibold text-highlighted">{{ d.id }}</p>
              <p class="text-xs text-muted">{{ d.date }} · {{ d.appliances }} appliances</p>
            </div>
            <UBadge color="neutral" variant="subtle" size="xs">Type {{ d.type }}</UBadge>
          </div>
          <p class="mt-2 text-xs text-dimmed">{{ SCENARIO_TYPES[d.type] }}</p>
          <div class="mt-3 flex items-center justify-between text-sm">
            <span class="text-muted">No scheduling {{ euro(d.naiveCost) }}</span>
            <span class="font-medium text-success">save up to {{ euro(d.achievableSaving) }}</span>
          </div>
        </UCard>
      </NuxtLink>
    </div>
  </div>
</template>
