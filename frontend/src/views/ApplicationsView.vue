<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Badge from '@/components/ui/Badge.vue'
import { applicationsApi } from '@/api'
import type { ApplicationSummary } from '@/types/dashboard'

const apps = ref<ApplicationSummary[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    const { data } = await applicationsApi.list()
    apps.value = data.applications
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <DashboardLayout>
    <div class="animate-fade-in space-y-5">
      <div>
        <h1 class="text-lg font-semibold text-slate-900 dark:text-white">Applications</h1>
        <p class="text-sm text-surface-muted">Registered apps from YAML registry</p>
      </div>

      <div class="dashboard-grid md:grid-cols-2 xl:grid-cols-3">
        <RouterLink
          v-for="app in apps"
          :key="app.id"
          :to="`/applications/${app.id}`"
          class="block rounded-xl border border-surface-border bg-surface-raised p-4 shadow-card transition hover:border-brand-500/30"
        >
          <div class="flex items-start justify-between gap-2">
            <div>
              <h2 class="font-semibold text-slate-900 dark:text-white">{{ app.name }}</h2>
              <p class="text-xs text-surface-muted">{{ app.type }} · {{ app.environment }}</p>
            </div>
            <Badge :variant="app.health === 'healthy' ? 'success' : 'warning'" size="sm">
              {{ app.health_score }}
            </Badge>
          </div>
          <p class="mt-2 text-sm text-surface-muted">{{ app.domain || app.root_path }}</p>
          <div class="mt-3 flex gap-2">
            <Badge size="sm">{{ app.status }}</Badge>
            <Badge :variant="app.enabled ? 'success' : 'neutral'" size="sm">
              {{ app.enabled ? 'Enabled' : 'Disabled' }}
            </Badge>
          </div>
        </RouterLink>
      </div>

      <p v-if="!apps.length && !loading" class="text-sm text-surface-muted">No applications found.</p>
    </div>
  </DashboardLayout>
</template>
