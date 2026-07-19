<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { healthApi, monitoringApi, securityApi, serverApi } from '@/api'
import { REALTIME_POLL_MS } from '@/config/polling'
import { useAuthStore } from '@/stores/auth'
import { usePolling } from '@/composables/usePolling'
import { Permission } from '@/lib/permissions'
import { usePermissions } from '@/composables/usePermissions'
import type { IntegrationsResponse, PortsResponse, ReadinessResponse } from '@/types/dashboard'
import type { AccessAttemptEntry, IpBlacklistEntry } from '@/types/security'

const router = useRouter()
const auth = useAuthStore()
const { can } = usePermissions()
const canManageSecurity = computed(() => can(Permission.SYSTEM_ADMIN) || !!auth.user?.is_superuser)

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

const blacklist = ref<IpBlacklistEntry[]>([])
const attempts = ref<AccessAttemptEntry[]>([])
const securityMessage = ref<string | null>(null)
const securityLoading = ref(false)

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

async function loadSecurity() {
  if (!canManageSecurity.value) return
  securityLoading.value = true
  try {
    const [b, a] = await Promise.all([
      securityApi.blacklist(true),
      securityApi.attempts(40),
    ])
    blacklist.value = b.data.entries
    attempts.value = a.data.attempts
  } catch {
    blacklist.value = []
    attempts.value = []
  } finally {
    securityLoading.value = false
  }
}

async function unlockIp(entry: IpBlacklistEntry) {
  securityMessage.value = null
  try {
    const { data } = await securityApi.unlock(entry.id, 'Unlocked from Settings')
    securityMessage.value = data.message
    await loadSecurity()
  } catch (e) {
    securityMessage.value = e instanceof Error ? e.message : 'Unlock failed'
  }
}

async function handleLogout() {
  await auth.logout()
  await router.replace({ name: 'login' })
}

function refreshAll() {
  refreshReadiness()
  refreshPorts()
  refreshIntegrations()
  loadProfile()
  loadSecurity()
}

onMounted(refreshAll)
</script>

<template>
  <DashboardLayout @refresh="refreshAll">
    <div class="animate-fade-in space-y-5">
      <Card padding="none">
        <div class="divide-y divide-surface-border">
          <div v-if="auth.user" class="flex items-center gap-4 p-4 md:p-5">
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
          <div v-else class="p-5">
            <p class="text-sm text-surface-muted">Loading profile…</p>
          </div>

          <dl v-if="auth.user" class="divide-y divide-surface-border text-sm">
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

      <Card
        v-if="canManageSecurity"
        title="Access security"
        subtitle="IP blacklist and access traces"
      >
        <p v-if="securityMessage" class="mb-3 text-sm text-emerald-700 dark:text-emerald-300">
          {{ securityMessage }}
        </p>

        <h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-surface-muted">
          Blacklisted IPs
        </h3>
        <div v-if="securityLoading" class="text-sm text-surface-muted">Loading…</div>
        <div v-else-if="!blacklist.length" class="mb-4 text-sm text-surface-muted">
          No active IP blocks.
        </div>
        <div v-else class="mb-5 max-h-48 space-y-2 overflow-y-auto">
          <div
            v-for="entry in blacklist"
            :key="entry.id"
            class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-border px-3 py-2 text-sm"
          >
            <div>
              <p class="font-mono font-medium">{{ entry.ip_address }}</p>
              <p class="text-xs text-surface-muted">
                {{ entry.reason }} · {{ entry.failed_attempt_count }} fails ·
                {{ new Date(entry.blocked_at).toLocaleString() }}
              </p>
              <p v-if="entry.last_device_fingerprint" class="truncate text-[10px] text-surface-muted">
                fp {{ entry.last_device_fingerprint.slice(0, 16) }}…
              </p>
            </div>
            <button
              type="button"
              class="rounded-lg border border-surface-border px-2.5 py-1 text-xs hover:bg-slate-50 dark:hover:bg-slate-800"
              @click="unlockIp(entry)"
            >
              Unlock IP
            </button>
          </div>
        </div>

        <h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-surface-muted">
          Recent access attempts
        </h3>
        <div class="max-h-56 overflow-auto rounded-lg border border-surface-border">
          <table class="w-full text-left text-xs">
            <thead class="sticky top-0 bg-surface-raised text-surface-muted">
              <tr>
                <th class="px-2 py-1.5">When</th>
                <th class="px-2 py-1.5">IP</th>
                <th class="px-2 py-1.5">Event</th>
                <th class="px-2 py-1.5">Identity</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in attempts"
                :key="row.id"
                class="border-t border-surface-border"
              >
                <td class="px-2 py-1.5 whitespace-nowrap">
                  {{ new Date(row.attempted_at).toLocaleString() }}
                </td>
                <td class="px-2 py-1.5 font-mono">{{ row.ip_address }}</td>
                <td class="px-2 py-1.5">
                  <Badge
                    :variant="row.success ? 'success' : row.event_type === 'access_probe' ? 'neutral' : 'warning'"
                    size="sm"
                  >
                    {{ row.event_type }}
                  </Badge>
                </td>
                <td class="max-w-[8rem] truncate px-2 py-1.5">
                  {{ row.username_or_email || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
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
