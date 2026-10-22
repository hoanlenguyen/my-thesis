<script setup lang="ts">
const { data: households, status } = await useHouseholds()
const { data: benchmarks } = await useBenchmarks()
const { data: fullPeriod } = await useFullPeriod()
const bestPerYear = (house: number) => {
  const h = fullPeriod.value?.households.find(x => x.house === house)
  return h?.totals.milp ? (h.totals.milp.saving / h.recordedDays) * 365 : null
}

const daysOf = (house: number) =>
  (benchmarks.value ?? []).flatMap(b => b.scenarios.filter(s => s.house === house)).length
const scheduledKinds = (h: { appliances: { kind: string, scheduled: boolean }[] }) =>
  [...new Set(h.appliances.filter(a => a.scheduled).map(a => a.kind))]
</script>

<template>
  <div class="space-y-5">
    <div>
      <h1 class="text-2xl font-semibold text-highlighted">Households</h1>
      <p class="mt-1 text-sm text-muted max-w-3xl">
        The 18 UK households of the REFIT dataset whose appliance cycles make up the benchmark. Each profile shows all
        monitored appliances and when the household typically uses them, from its 2013–2015 recordings. They are
        numbered 1 to 18 here; REFIT numbers its 20 houses 1 to 21 without a house 14, and houses 12 and 19 are left
        out (no monitored laundry or dishwasher, and a washing-machine monitor that never records heating), so each
        household also shows its REFIT number.
      </p>
    </div>

    <div v-if="households" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <NuxtLink v-for="h in households" :key="h.house" :to="`/households/${householdNo(h.house)}`">
        <UCard class="hover:ring-primary/50 transition h-full">
          <div class="flex items-start justify-between gap-2">
            <div class="flex items-center gap-2">
              <div class="rounded-lg p-2 bg-primary/10">
                <UIcon name="i-lucide-house" class="size-5 text-primary" />
              </div>
              <div>
                <p class="font-semibold text-highlighted">Household {{ householdNo(h.house) }}</p>
                <p class="text-xs text-muted">REFIT house {{ h.house }} · {{ h.appliances.length }} monitored appliances · {{ h.days }} recorded days</p>
              </div>
            </div>
            <UBadge color="neutral" variant="subtle" size="xs">{{ daysOf(h.house) }} benchmark days</UBadge>
          </div>
          <div class="mt-3 flex flex-wrap gap-1.5">
            <UBadge v-for="k in scheduledKinds(h)" :key="k" :icon="applianceIcon(k)" color="primary" variant="subtle" size="xs">
              {{ applianceName(k, k) }}
            </UBadge>
          </div>
          <p v-if="bestPerYear(h.house) != null" class="mt-2 text-xs text-success">
            Best possible saving ≈ {{ euro(bestPerYear(h.house)) }} per year at today's prices
          </p>
        </UCard>
      </NuxtLink>
    </div>
    <div v-else-if="status === 'pending'" class="h-48 rounded-lg bg-elevated/40 animate-pulse" />
    <p v-else class="text-sm text-muted">
      Household profiles are not exported yet. Run <code>uv run python tools/export_household_profiles.py</code>.
    </p>
  </div>
</template>
