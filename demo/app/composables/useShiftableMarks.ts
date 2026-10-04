// Which non-scheduled appliances the viewer considers (partly) shiftable, per household. Display only:
// the recorded results never schedule them. Defaults to computer, television and washer-dryer; the
// viewer's choices are kept in the browser (localStorage) and survive reloads.
import { useLocalStorage } from '@vueuse/core'

const marks = useLocalStorage<Record<string, boolean>>('hems-demo-partly-shiftable', {})

export function useShiftableMarks() {
  const key = (house: number | null | undefined, name: string) => `${house ?? '-'}:${name}`
  const isShiftable = (house: number | null | undefined, name: string, kind: string) =>
    marks.value[key(house, name)] ?? DISPLAY_SHIFTABLE.has(kind)
  const setShiftable = (house: number | null | undefined, name: string, value: boolean) => {
    marks.value = { ...marks.value, [key(house, name)]: value }
  }
  const reset = (house: number | null | undefined) => {
    marks.value = Object.fromEntries(Object.entries(marks.value).filter(([k]) => !k.startsWith(`${house ?? '-'}:`)))
  }
  return { isShiftable, setShiftable, reset }
}
