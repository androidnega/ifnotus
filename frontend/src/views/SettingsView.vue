<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { healthApi, monitoringApi, serverApi } from '@/api'
import { REALTIME_POLL_MS } from '@/config/polling'
import { useAuthStore } from '@/stores/auth'
import { usePolling } from '@/composables/usePolling'
import type { IntegrationsResponse, PortsResponse, ReadinessResponse } from '@/types/dashboard'

const router = useRouter()
const auth = useAuthStore()

const { data: readiness, refresh: refreshReadiness } = usePolling<ReadinessResponse>(
  async () => (await healthApi.readiness()).data,
  REALTIME_POLL_MS,
)

const { data: ports, refresh: refreshPorts } = usePolling<PortsResponse>(
  async () => (await serverApi.ports()).data,
  REALTIME_POLL_MS,
  { requiresAuth: true },
)

const { data: integrations, refresh: refreshIntegrations } = usePolling<IntegrationsResponse>(
  async () => (await monitoringApi.integrations()).data,
  REALTIME_POLL_MS,
  { requiresAuth: true },
)

const integrationEntries = computed(() => {
  if (!integrations.value) return []
  return Object.entries(integrations.value).map(([name, info]) => ({
    name,
    configured: info.configured,
    status: String(info.status ?? 'unknown'),
  }))
})

const displayName = computed(
  () => auth.user?.full_name || auth.user?.username || 'Operator',
)

const userInitial = computed(() =>
  (auth.user?.username || 'U').charAt(0).toUpperCase(),
)

function formatRole(role: string) {
  return role
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

async function loadProfile() {
  if (!auth.user) {
    try {
      await auth.fetchUser()
    } catch {
      /* profile load optional on settings page */
    }
  }
}

async function handleLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}

function refreshAll() {
  refreshReadiness()
  refreshPorts()
  refreshIntegrations()
  loadProfile()
}

onMounted(refreshAll)
</script>

<template>
  <DashboardLayout @refresh="refreshAll">
    <div class="animate-fade-in space-y-5">
      <Card padding="none">
        <div v-if="auth.user" class="divide-y divide-surface-border">
          <div class="flex items-center gap-4 p-4 md:p-5">
            <div
              class="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-brand-500/15 text-lg font-semibold text-brand-700 dark:text-brand-300"
              aria-hidden="true"
            >
              {{ userInitial }}
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-slate-900 dark:text-white">
                {{ displayName }}
              </p>
              <p class="truncate text-sm text-surface-muted">@{{ auth.user.username }}</p>
              <div class="mt-2 flex flex-wrap gap-1.5">
                <Badge
                  v-for="role in auth.user.roles"
                  :key="role"
                  variant="info"
                  size="sm"
                >
                  {{ formatRole(role) }}
                </Badge>
              </div>
            </div>
          </div>

          <dl class="divide-y divide-surface-border text-sm">
            <div class="grid grid-cols-[6.5rem_1fr] items-center gap-x-4 px-4 py-3 md:px-5">
              <dt class="text-surface-muted">Username</dt>
              <dd class="font-medium text-slate-900 dark:text-white">{{ auth.user.username }}</dd>
            </div>
            <div class="grid grid-cols-[6.5rem_1fr] items-center gap-x-4 px-4 py-3 md:px-5">
              <dt class="text-surface-muted">Email</dt>
              <dd class="truncate font-medium text-slate-900 dark:text-white">
                {{ auth.user.email }}
              </dd>
            </div>
            <div class="grid grid-cols-[6.5rem_1fr] items-center gap-x-4 px-4 py-3 md:px-5">
              <dt class="text-surface-muted">Status</dt>
              <dd>
                <Badge :variant="auth.user.is_active ? 'success' : 'danger'" dot size="sm">
                  {{ auth.user.is_active ? 'Active' : 'Inactive' }}
                </Badge>
              </dd>
            </div>
          </dl>

          <div class="flex justify-end bg-slate-50/80 px-4 py-3 dark:bg-slate-900/40 md:px-5">
            <button
              type="button"
              class="rounded-lg px-4 py-2 text-sm font-medium text-red-600 transition hover:bg-red-500/10 dark:text-red-400"
              @click="handleLogout"
            >
              Sign out
            </button>
          </div>
        </div>

        <div v-else class="p-5">
          <p class="text-sm text-surface-muted">Loading profile…</p>
        </div>
      </Card>

      <Card title="Platform Health">
        <div class="mb-4 flex flex-wrap gap-4">
          <div>
            <p class="text-xs text-surface-muted">Readiness</p>
            <Badge
              :variant="readiness?.status === 'healthy' ? 'success' : 'warning'"
              dot
              class="mt-1"
            >
              {{ readiness?.status ?? '—' }}
            </Badge>
          </div>
          <div>
            <p class="text-xs text-surface-muted">Environment</p>
            <p class="font-medium">{{ readiness?.environment ?? '—' }}</p>
          </div>
          <div>
            <p class="text-xs text-surface-muted">Version</p>
            <p class="font-medium">{{ readiness?.version ?? '—' }}</p>
          </div>
        </div>

        <div class="space-y-2">
          <div
            v-for="component in readiness?.components ?? []"
            :key="component.name"
            class="flex items-center justify-between rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-900"
          >
            <span class="font-medium capitalize">{{ component.name }}</span>
            <div class="flex items-center gap-3">
              <span v-if="component.latency_ms" class="text-xs text-surface-muted">
                {{ component.latency_ms.toFixed(1) }} ms
              </span>
              <Badge :variant="component.status === 'healthy' ? 'success' : 'danger'" dot>
                {{ component.status }}
              </Badge>
            </div>
          </div>
        </div>
      </Card>

      <Card title="Integrations" subtitle="Live collector status">
        <div class="space-y-2">
          <div
            v-for="item in integrationEntries"
            :key="item.name"
            class="flex items-center justify-between rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-900"
          >
            <span class="font-medium capitalize">{{ item.name }}</span>
            <div class="flex items-center gap-2">
              <span class="text-xs text-surface-muted">
                {{ item.configured ? 'configured' : 'not configured' }}
              </span>
              <Badge
                :variant="
                  item.status === 'healthy'
                    ? 'success'
                    : item.status === 'degraded'
                      ? 'warning'
                      : 'neutral'
                "
                dot
                size="sm"
              >
                {{ item.status }}
              </Badge>
            </div>
          </div>
        </div>
      </Card>

      <Card title="Monitored Ports" subtitle="Services IFNOTUS tracks for outages">
        <p class="mb-3 text-sm text-surface-muted">
          Expected:
          <span class="font-mono">{{ ports?.expected_ports?.join(', ') ?? '—' }}</span>
        </p>
        <div
          v-if="ports?.missing_ports?.length"
          class="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300"
        >
          Not listening: {{ ports.missing_ports.join(', ') }}
        </div>
        <p v-else class="text-sm text-emerald-600 dark:text-emerald-400">
          All expected ports are listening.
        </p>
      </Card>
    </div>
  </DashboardLayout>
</template>
