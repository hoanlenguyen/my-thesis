<script setup lang="ts">
// Header layout adapted from Low-carbon-alerts (app/layouts/app.vue), without auth or notifications.
const route = useRoute()
const navItems = [
  { label: 'Which system saves?', icon: 'i-lucide-chart-column', to: '/' },
  { label: 'Households', icon: 'i-lucide-house', to: '/households' },
  { label: 'Daily recommendations', icon: 'i-lucide-calendar-clock', to: '/days' },
  { label: "Today's price", icon: 'i-lucide-zap', to: '/today' }
]
const isActive = (to: string) => (to === '/' ? route.path === '/' : route.path.startsWith(to))
</script>

<template>
  <div class="min-h-screen flex flex-col bg-default">
    <header class="border-b border-default px-4 sm:px-6 h-14 flex items-center justify-between shrink-0">
      <NuxtLink to="/" class="flex items-center gap-2 font-semibold text-highlighted hover:text-primary transition-colors">
        <div class="size-7 rounded-md bg-primary/15 flex items-center justify-center">
          <UIcon name="i-lucide-house-plug" class="size-4 text-primary" />
        </div>
        <span>HEMS agent demo</span>
      </NuxtLink>
      <nav class="flex items-center gap-1">
        <UButton
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :icon="item.icon"
          size="sm"
          :color="isActive(item.to) ? 'primary' : 'neutral'"
          :variant="isActive(item.to) ? 'soft' : 'ghost'">
          <span class="hidden sm:inline">{{ item.label }}</span>
        </UButton>
        <UColorModeButton size="sm" />
      </nav>
    </header>

    <main class="flex-1 w-full max-w-6xl mx-auto px-4 sm:px-6 py-6">
      <slot />
    </main>

    <footer class="border-t border-default px-4 sm:px-6 py-3 text-xs text-dimmed">
      Replay of recorded thesis results (no system is run live). Appliance cycles: REFIT dataset.
      Prices: Nord Pool FI via Sähkötin and Elering. Master's thesis, University of Oulu.
    </footer>
  </div>
</template>
