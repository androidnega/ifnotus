<script setup lang="ts">
import { useRouter } from 'vue-router'
import { IconChart, IconDeploy, IconRefresh, IconServer, IconSettings } from '@/components/icons'

defineProps<{
  refreshing?: boolean
}>()

const emit = defineEmits<{
  refresh: []
}>()

const router = useRouter()

const actions = [
  {
    id: 'monitoring',
    label: 'Monitoring',
    icon: IconChart,
    run: () => router.push({ name: 'monitoring' }),
  },
  {
    id: 'ports',
    label: 'Ports',
    icon: IconServer,
    run: () => router.push({ name: 'servers' }),
  },
  {
    id: 'apps',
    label: 'Apps',
    icon: IconDeploy,
    run: () => router.push({ name: 'applications' }),
  },
  {
    id: 'operations',
    label: 'Ops',
    icon: IconServer,
    run: () => router.push({ name: 'operations' }),
  },
  {
    id: 'refresh',
    label: 'Refresh',
    icon: IconRefresh,
    run: () => emit('refresh'),
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: IconSettings,
    run: () => router.push({ name: 'settings' }),
  },
] as const
</script>

<template>
  <div
    class="-mx-1 overflow-x-auto overscroll-x-contain pb-0.5 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
    role="group"
    aria-label="Quick actions"
  >
    <div class="grid min-w-0 grid-flow-col auto-cols-fr gap-2 px-1 sm:grid-flow-row sm:grid-cols-5 sm:gap-2.5">
      <button
        v-for="action in actions"
        :key="action.id"
        type="button"
        class="inline-flex min-w-[5.5rem] max-w-full min-h-[2.75rem] items-center justify-center gap-2 rounded-xl border border-surface-border bg-slate-50/80 px-3 py-2 text-sm font-medium text-slate-800 transition-colors hover:border-brand-500/30 hover:bg-brand-500/5 dark:bg-slate-900/50 dark:text-slate-100 sm:min-w-0 sm:px-3.5 sm:py-2.5"
        @click="action.run()"
      >
        <component
          :is="action.icon"
          :size="16"
          class="shrink-0 text-surface-muted"
          :class="action.id === 'refresh' && refreshing ? 'animate-spin text-brand-500' : ''"
        />
        <span class="truncate">{{ action.label }}</span>
      </button>
    </div>
  </div>
</template>
