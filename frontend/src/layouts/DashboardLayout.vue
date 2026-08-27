<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppTopBar from '@/components/layout/AppTopBar.vue'
import { useThemeStore } from '@/stores/theme'
import { syncSiteDocumentTone } from '@/composables/useSiteTheme'

defineProps<{
  refreshing?: boolean
  /** Edge-to-edge main content (no outer padding). */
  flush?: boolean
}>()

defineEmits<{
  refresh: []
}>()

const route = useRoute()
const sidebarCollapsed = ref(false)
const mobileNavOpen = ref(false)

watch(
  () => route.fullPath,
  () => {
    mobileNavOpen.value = false
  },
)

onMounted(() => {
  document.documentElement.classList.add('control-ui')
  const theme = useThemeStore()
  document.documentElement.classList.toggle('dark', theme.isDark)
  document.documentElement.style.colorScheme = theme.isDark ? 'dark' : 'light'
})

onUnmounted(() => {
  document.documentElement.classList.remove('control-ui')
  syncSiteDocumentTone()
})
</script>

<template>
  <div class="control-shell flex h-screen overflow-hidden bg-surface">
    <div
      v-if="mobileNavOpen"
      class="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm lg:hidden"
      aria-hidden="true"
      @click="mobileNavOpen = false"
    />

    <AppSidebar
      :collapsed="sidebarCollapsed"
      :mobile-open="mobileNavOpen"
      @close-mobile="mobileNavOpen = false"
      @toggle-collapse="sidebarCollapsed = !sidebarCollapsed"
    />

    <div class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      <AppTopBar
        class="shrink-0"
        :refreshing="refreshing"
        @toggle-mobile-nav="mobileNavOpen = !mobileNavOpen"
        @refresh="$emit('refresh')"
      />

      <main class="control-main min-h-0 flex-1 overflow-y-auto overscroll-contain" :class="{ 'control-main--flush': flush }">
        <div class="control-main-inner" :class="{ 'control-main-inner--flush': flush }">
          <slot />
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.control-main {
  width: 100%;
  padding: 1rem 1rem 1.5rem;
}
.control-main-inner {
  width: 100%;
  max-width: none;
  margin: 0;
}
@media (min-width: 768px) {
  .control-main {
    padding: 1.15rem 1.35rem 1.75rem;
  }
}
@media (min-width: 1280px) {
  .control-main {
    padding: 1.25rem 1.75rem 2rem;
  }
}
@media (min-width: 1536px) {
  .control-main {
    padding: 1.4rem 2.25rem 2.4rem;
  }
}
@media (min-width: 1800px) {
  .control-main {
    padding: 1.5rem 2.75rem 2.75rem;
  }
}
.control-main--flush {
  padding: 0 !important;
}
.control-main-inner--flush {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}
</style>
