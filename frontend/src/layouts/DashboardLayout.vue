<script setup lang="ts">
import { ref } from 'vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppTopBar from '@/components/layout/AppTopBar.vue'

defineProps<{
  refreshing?: boolean
}>()

defineEmits<{
  refresh: []
}>()

const sidebarCollapsed = ref(false)
const mobileNavOpen = ref(false)
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-surface">
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

      <main class="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 md:p-5 lg:p-6">
        <slot />
      </main>
    </div>
  </div>
</template>
