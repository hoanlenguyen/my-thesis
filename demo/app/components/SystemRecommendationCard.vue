<script setup lang="ts">
// A system's daily recommendation, styled after Low-carbon-alerts' RecommendationCard.
import type { Appliance, RunResult } from '~/composables/useDemoData'

// naiveCost: the cost savings are measured against (no scheduling, or on the Try page the highest-cost system)
const props = withDefaults(defineProps<{ result: RunResult, appliances: Appliance[], naiveCost: number, milpCost: number, referenceLabel?: string }>(),
  { referenceLabel: 'no scheduling' })

const group = computed(() => groupBadge(props.result.system))
const saving = computed(() => props.naiveCost - (props.result.feasible ? (props.result.costEur ?? props.naiveCost) : props.naiveCost))
const share = computed(() => {
  const achievable = props.naiveCost - props.milpCost
  return achievable >= 0.005 ? saving.value / achievable : null
})
const gap = computed(() => props.result.costEur == null ? null : ((props.result.costEur - props.milpCost) / props.milpCost) * 100)
</script>

<template>
  <UPageCard variant="subtle">
    <template #header>
      <div class="flex flex-wrap items-center justify-between gap-2 w-full">
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-sparkles" class="size-4 text-primary shrink-0" />
          <span class="font-semibold text-sm text-highlighted">{{ result.label }}</span>
          <UBadge :color="group.color" variant="subtle" size="xs">{{ group.label }}</UBadge>
          <span v-if="MODEL_LABELS[result.model]" class="text-xs text-dimmed">{{ MODEL_LABELS[result.model] }}</span>
        </div>
        <UBadge v-if="result.feasible" color="success" variant="subtle" size="sm" icon="i-lucide-circle-check">
          Valid schedule
        </UBadge>
        <UBadge v-else color="error" variant="subtle" size="sm" icon="i-lucide-triangle-alert">
          Breaks a household limit
        </UBadge>
      </div>
    </template>

    <div class="space-y-3">
      <!-- start times -->
      <div class="flex flex-wrap gap-2">
        <UBadge
          v-for="a in appliances"
          :key="a.id"
          :icon="APPLIANCE_ICONS[a.kind] ?? 'i-lucide-plug'"
          color="neutral"
          variant="subtle"
          size="md">
          {{ applianceName(a.id, a.kind) }}:
          <b class="ml-1">{{ result.starts[a.id] != null ? slotTime(result.starts[a.id]!) : 'not scheduled' }}</b>
        </UBadge>
      </div>

      <!-- money -->
      <div class="grid grid-cols-3 gap-2">
        <div class="rounded-lg bg-elevated/40 px-3 py-2">
          <p class="text-[11px] text-muted">Cost of the day</p>
          <p class="text-lg font-bold tabular-nums text-highlighted">{{ euro(result.costEur, 3) }}</p>
        </div>
        <div class="rounded-lg px-3 py-2" :class="saving > 0.0005 ? 'bg-success/10' : 'bg-elevated/40'">
          <p class="text-[11px] text-muted">Saving vs. {{ referenceLabel }}</p>
          <p class="text-lg font-bold tabular-nums" :class="saving > 0.0005 ? 'text-success' : 'text-muted'">{{ euro(saving, 3) }}</p>
        </div>
        <div class="rounded-lg bg-elevated/40 px-3 py-2">
          <p class="text-[11px] text-muted">Of the possible saving</p>
          <p class="text-lg font-bold tabular-nums text-highlighted">{{ share == null ? '–' : pct(share * 100, 0) }}</p>
        </div>
      </div>
      <p v-if="gap != null" class="text-xs text-dimmed">
        {{ gap < 0.005 ? 'Optimal cost.' : `${gap.toFixed(2)} % above the optimal cost.` }}
        <template v-if="result.latencyS != null && result.latencyS > 0.05"> Took {{ result.latencyS.toFixed(1) }} s.</template>
        <template v-if="result.usd"> API cost ${{ result.usd.toFixed(4) }}.</template>
      </p>

      <!-- explanation -->
      <div v-if="result.message" class="flex items-start gap-2 rounded-lg bg-elevated/40 px-3 py-2">
        <UIcon name="i-lucide-message-square-quote" class="size-3.5 text-primary shrink-0 mt-0.5" />
        <p class="text-xs text-muted leading-relaxed">{{ result.message }}</p>
      </div>

      <!-- violations -->
      <ul v-if="result.violations.length" class="text-xs text-error space-y-0.5">
        <li v-for="v in result.violations" :key="v" class="flex items-start gap-1.5">
          <UIcon name="i-lucide-x" class="size-3 mt-0.5 shrink-0" />{{ v }}
        </li>
      </ul>
    </div>
  </UPageCard>
</template>
