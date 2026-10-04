// Shared by the day page and the household page: the rows of "When each system runs the appliances".
import type { DayDetail, FixedRow, Household, RunResult, UsualRow } from '~/composables/useDemoData'

export function useDayComparison(
  day: Ref<DayDetail | null | undefined>,
  households: Ref<Household[] | null | undefined>,
  run: Ref<number>,
  showLocal: Ref<boolean>
) {
  const household = computed(() => households.value?.find(h => h.house === day.value?.house))

  // One result per system for the chosen LLM run (deterministic systems have run 0).
  const results = computed<RunResult[]>(() =>
    (day.value?.results ?? []).filter(r => (r.run === 0 || r.run === run.value) && (showLocal.value || r.model !== 'gpt-oss-20b'))
  )

  // When this household usually runs the kinds of appliance being scheduled today (if it owns them).
  const usual = computed<UsualRow[]>(() => {
    const kinds = new Set((day.value?.appliances ?? []).map(a => a.kind))
    return (household.value?.appliances ?? [])
      .filter(a => kinds.has(a.kind))
      .map(a => ({ name: a.name, kind: a.kind, hourly: a.hourly }))
  })

  // The household's appliances that no system schedules, with their typical use.
  const { isShiftable } = useShiftableMarks()
  const fixed = computed<FixedRow[]>(() =>
    (day.value?.fixedAppliances ?? []).map((f) => {
      const p = household.value?.appliances.find(a => a.name === f.id)
      return {
        id: f.id, kind: f.kind, ratedKw: p?.ratedKw ?? f.ratedKw, hourly: p?.hourly ?? null,
        shiftable: isShiftable(day.value?.house, f.id, f.kind)
      }
    })
  )

  return { household, results, usual, fixed }
}
