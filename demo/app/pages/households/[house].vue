<script setup lang="ts">
const route = useRoute()
const houseNo = computed(() => Number(route.params.house))
const { data: households } = await useHouseholds()
const { data: fullPeriod } = await useFullPeriod()
const { data: benchmarks } = await useBenchmarks()

const household = computed(() => households.value?.find(h => h.house === houseNo.value))
const appliances = computed(() =>
  [...(household.value?.appliances ?? [])].sort((a, b) => Number(b.scheduled) - Number(a.scheduled) || b.kwhPerDay - a.kwhPerDay)
)
const days = computed(() =>
  (benchmarks.value ?? []).flatMap(b => b.scenarios.filter(s => s.house === houseNo.value).map(s => ({ ...s, bench: b.id, benchLabel: b.label })))
)
const { isShiftable, setShiftable, reset: resetMarks } = useShiftableMarks()
const role = (a: { name: string, kind: string, scheduled: boolean }) =>
  applianceRole(a, isShiftable(houseNo.value, a.name, a.kind))
const totalKwh = computed(() => appliances.value.reduce((s, a) => s + a.kwhPerDay, 0))

// "When each system runs the appliances" for one of the household's benchmark days.
const pickedKey = ref('')
const picked = computed(() => days.value.find(d => `${d.bench}/${d.id}` === pickedKey.value) ?? days.value[0])
const { data: day } = await useDay(() => picked.value?.bench ?? 'main', () => picked.value?.id ?? '')
const run = ref(1)
const showLocal = ref(false)
const { results, usual, fixed } = useDayComparison(day, households, run, showLocal)
const hasLocal = computed(() => day.value?.results.some(r => r.model === 'gpt-oss-20b'))
</script>

<template>
  <div v-if="household" class="space-y-5">
    <div>
      <UButton to="/households" icon="i-lucide-arrow-left" size="xs" variant="ghost" color="neutral" class="-ml-2 mb-1">
        All households
      </UButton>
      <h1 class="text-2xl font-semibold text-highlighted">Household {{ household.house }}</h1>
      <p class="text-sm text-muted">
        REFIT recordings {{ household.firstDay }} to {{ household.lastDay }} ({{ household.days }} complete days) ·
        monitored appliances use {{ totalKwh.toFixed(1) }} kWh per day on average
      </p>
    </div>

    <FullPeriodCard :house="houseNo" :data="fullPeriod" />

    <UCard :ui="{ body: 'p-0 sm:p-0' }">
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-plug-zap" class="size-4 text-primary" />
          <span class="font-semibold text-sm text-highlighted">Appliances and when they are typically used</span>
        </div>
      </template>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="text-xs text-muted border-b border-default">
            <tr>
              <th class="text-center font-medium px-2 py-2 w-20">
                <UTooltip text="Tick the appliances you consider partly shiftable (display only: the benchmark schedules only the washing machine, dishwasher and tumble dryer)">
                  <span class="inline-flex items-center gap-1">Partly shiftable <UIcon name="i-lucide-info" class="size-3" /></span>
                </UTooltip>
              </th>
              <th class="text-left font-medium px-4 py-2">Appliance</th>
              <th class="text-right font-medium px-3 py-2">Power when on</th>
              <th class="text-right font-medium px-3 py-2">kWh / day</th>
              <th class="text-right font-medium px-3 py-2">Used on</th>
              <th class="text-left font-medium px-4 py-2 min-w-72">Typical use by hour (darker = more often)</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in appliances" :key="a.name" class="border-b border-default last:border-0 align-middle">
              <td class="px-2 py-2 text-center">
                <UTooltip v-if="a.scheduled" text="Scheduled by every system in the benchmark">
                  <UIcon name="i-lucide-calendar-check" class="size-4 text-primary" />
                </UTooltip>
                <UCheckbox
                  v-else
                  class="justify-center"
                  :model-value="isShiftable(houseNo, a.name, a.kind)"
                  :aria-label="`${applianceName(a.name, a.kind)} is partly shiftable`"
                  @update:model-value="(v) => setShiftable(houseNo, a.name, v === true)" />
              </td>
              <td class="px-4 py-2">
                <div class="flex items-center gap-2">
                  <UIcon :name="applianceIcon(a.kind)" class="size-4 text-muted shrink-0" />
                  <span class="text-highlighted">{{ applianceName(a.name, a.kind) }}</span>
                  <UBadge :color="role(a).color" variant="subtle" size="xs">{{ role(a).label }}</UBadge>
                </div>
              </td>
              <td class="px-3 py-2 text-right tabular-nums">{{ a.ratedKw.toFixed(2) }} kW</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ a.kwhPerDay.toFixed(2) }}</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ Math.round(a.daysUsedShare * 100) }} % of days</td>
              <td class="px-4 py-2"><UsageStrip :share="a.hourly" compact /></td>
            </tr>
            <tr>
              <td class="px-2 pb-2 text-center">
                <UButton size="xs" variant="link" color="neutral" class="p-0 text-[10px]" @click="resetMarks(houseNo)">reset</UButton>
              </td>
              <td colspan="4" />
              <td class="px-4 pb-2">
                <div class="grid grid-cols-24 text-[9px] text-dimmed">
                  <span v-for="h in 24" :key="h" class="text-center">{{ (h - 1) % 3 === 0 ? String(h - 1).padStart(2, '0') : '' }}</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="px-4 py-3 text-xs text-dimmed border-t border-default">
        Times are UK local time of the recording. "Power when on" is the median power while the appliance draws more than
        its standby level; washing machines spend most of a cycle well below their heating peak.
      </p>
    </UCard>

    <UCard v-if="days.length">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <UIcon name="i-lucide-calendar-range" class="size-4 text-primary" />
            <span class="font-semibold text-sm text-highlighted">When each system runs the appliances, compared with this household's usual times</span>
          </div>
          <div class="flex items-center gap-3">
            <div class="flex items-center gap-1">
              <span class="text-xs text-muted mr-1">LLM run</span>
              <UButton v-for="n in [1, 2, 3]" :key="n" size="xs" :variant="run === n ? 'soft' : 'ghost'" :color="run === n ? 'primary' : 'neutral'" @click="run = n">
                {{ n }}
              </UButton>
            </div>
            <USwitch v-if="hasLocal" v-model="showLocal" label="Local model" size="sm" />
          </div>
        </div>
      </template>

      <!-- day picker -->
      <div class="flex flex-wrap gap-1.5 mb-3">
        <button
          v-for="d in days"
          :key="d.bench + d.id"
          class="rounded-lg border px-2.5 py-1.5 text-left transition"
          :class="picked && `${picked.bench}/${picked.id}` === `${d.bench}/${d.id}` ? 'border-primary bg-primary/10' : 'border-default hover:border-primary/50'"
          @click="pickedKey = `${d.bench}/${d.id}`">
          <p class="text-xs font-medium text-highlighted">{{ d.id }} · {{ d.date }}</p>
          <p class="text-[10px] text-muted">{{ SCENARIO_TYPES[d.type] }} · save up to {{ euro(d.achievableSaving) }}</p>
        </button>
      </div>

      <div v-if="day && picked">
        <ScheduleTimeline
          :appliances="day.appliances"
          :results="results"
          :naive-cost="day.naiveCost"
          :milp-cost="day.milpCost"
          :usual="usual"
          :fixed="fixed" />
        <div class="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p class="text-xs text-dimmed max-w-3xl">
            No scheduling starts every cycle when it is ready ({{ euro(day.naiveCost, 3) }} that day). The cycles to schedule are
            recorded REFIT cycles drawn from all 18 households, so a day can include an appliance this household does not own;
            "Usually used" covers the ones it does own.
          </p>
          <UButton :to="`/days/${picked.bench}/${picked.id}`" size="xs" variant="soft" icon="i-lucide-arrow-right" trailing>
            Day details
          </UButton>
        </div>
      </div>
      <div v-else class="h-48 rounded-lg bg-elevated/40 animate-pulse" />
    </UCard>
  </div>
  <div v-else class="text-sm text-muted">Household not found.</div>
</template>
