<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { customersApi } from '@/api'
import PortalShell from '@/components/portal/PortalShell.vue'
import { getApiErrorMessage } from '@/lib/apiError'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import type { CustomerDashboard, CustomerEnvironment, HostingPlan } from '@/types/platform'

type HostingTab =
  | 'overview'
  | 'files'
  | 'databases'
  | 'domains'
  | 'email'
  | 'transfer'
  | 'apps'
  | 'backups'
  | 'logs'

const TABS: Array<{ id: HostingTab; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'files', label: 'Files' },
  { id: 'databases', label: 'Databases' },
  { id: 'domains', label: 'Domains' },
  { id: 'email', label: 'Email' },
  { id: 'transfer', label: 'Transfer' },
  { id: 'apps', label: 'Apps' },
  { id: 'backups', label: 'Backups' },
  { id: 'logs', label: 'Logs' },
]

const route = useRoute()
const router = useRouter()

const dash = ref<CustomerDashboard | null>(null)
const plans = ref<HostingPlan[]>([])
const loading = ref(true)
const error = ref('')
const tab = ref<HostingTab>('overview')

const environmentId = computed(() => String(route.params.environmentId || ''))

const env = computed<CustomerEnvironment | null>(() => {
  const id = environmentId.value
  if (!id || !dash.value) return null
  return dash.value.environments.find((e) => e.id === id) || null
})

const plan = computed(() => {
  const e = env.value
  if (!e || !dash.value) return null
  const sub = dash.value.subscriptions.find((s) => s.id === e.subscription_id)
  if (!sub) return null
  return plans.value.find((p) => p.id === sub.plan_id) || dash.value.plans?.find((p) => p.id === sub.plan_id) || null
})

const spec = computed(() => {
  const e = env.value
  const p = plan.value
  return {
    cpu: formatCpu(e?.cpu_limit ?? p?.cpu_cores ?? 0),
    ram: formatRamGb(e?.ram_limit_gb ?? p?.ram_gb ?? 0),
    disk: e?.storage_limit_gb ?? p?.storage_gb ?? 0,
  }
})

function accountTool(path: string, extraQuery: Record<string, string> = {}) {
  const id = environmentId.value
  const q = new URLSearchParams({ env: id, ...extraQuery })
  return `${path}?${q.toString()}`
}

function hostingHref(next: HostingTab) {
  if (next === 'overview') return `/hosting/${environmentId.value}`
  if (next === 'files') return `/hosting/${environmentId.value}/files`
  return `/hosting/${environmentId.value}?tab=${next}`
}

function goTab(next: HostingTab) {
  if (next === 'files') {
    void router.push({ name: 'hosting-files', params: { environmentId: environmentId.value } })
    return
  }
  tab.value = next
  const query = next === 'overview' ? {} : { tab: next }
  void router.replace({ name: 'hosting-panel', params: { environmentId: environmentId.value }, query })
}

function openLegacy(path: string, extraQuery: Record<string, string> = {}) {
  window.location.href = accountTool(path, extraQuery)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await customersApi.dashboard()
    dash.value = data
    plans.value = data.plans?.length ? data.plans : []
    const owned = data.environments.some((e) => e.id === environmentId.value)
    if (!owned) {
      error.value = 'This hosting service is not on your account.'
      return
    }
  } catch (e: unknown) {
    error.value = getApiErrorMessage(e, 'Could not load hosting panel.')
  } finally {
    loading.value = false
  }
}

watch(
  () => route.query.tab,
  (raw) => {
    const value = typeof raw === 'string' ? raw : ''
    if (TABS.some((t) => t.id === value)) {
      tab.value = value as HostingTab
    } else {
      tab.value = 'overview'
    }
  },
  { immediate: true },
)

watch(environmentId, () => {
  void load()
})

onMounted(() => {
  void load()
})
</script>

<template>
  <PortalShell mode="app" :email="dash?.customer.email" :display-name="dash?.customer.full_name" profile-menu>
    <div class="hosting">
      <header class="top">
        <div>
          <RouterLink class="back" :to="{ name: 'portal-dashboard' }">← Back to account</RouterLink>
          <h1>{{ env?.domain || 'Hosting' }}</h1>
          <p class="lede">Technical tools for this site — separate from billing and account settings.</p>
        </div>
        <p v-if="plan" class="plan-chip">{{ plan.name }}</p>
      </header>

      <nav class="tabs" aria-label="Hosting tools">
        <button
          v-for="item in TABS"
          :key="item.id"
          type="button"
          :class="{ on: tab === item.id }"
          @click="goTab(item.id)"
        >
          {{ item.label }}
        </button>
      </nav>

      <p v-if="loading" class="muted">Loading hosting…</p>
      <div v-else-if="error" class="p-card">
        <h2>Unavailable</h2>
        <p class="muted">{{ error }}</p>
        <RouterLink class="btn-primary" :to="{ name: 'portal-dashboard' }">Back to account</RouterLink>
      </div>

      <template v-else-if="env">
        <section v-if="tab === 'overview'" class="panel">
          <article class="p-card">
            <p class="kicker">Overview</p>
            <h2>{{ env.domain || 'Your site' }}</h2>
            <p class="muted">
              {{ spec.cpu }} vCPU · {{ spec.ram }} · {{ spec.disk }} GB disk · Status {{ env.status || '—' }}
            </p>
            <div class="actions">
              <a class="btn-primary" :href="accountTool('/account/files')">Open files</a>
              <a
                v-if="env.domain"
                class="btn-ghost"
                :href="`https://${env.domain}`"
                target="_blank"
                rel="noopener"
              >Open site</a>
              <RouterLink
                class="btn-ghost"
                :to="{ name: 'portal-dashboard', query: { panel: 'site', tab: 'ftp', env: environmentId } }"
              >
                FTP login
              </RouterLink>
            </div>
          </article>

          <div class="quick">
            <a v-for="item in TABS.filter((t) => t.id !== 'overview')" :key="item.id" :href="hostingHref(item.id)">
              {{ item.label }}
            </a>
          </div>
        </section>

        <section v-else class="panel p-card">
          <p class="kicker">{{ TABS.find((t) => t.id === tab)?.label }}</p>
          <h2>{{ TABS.find((t) => t.id === tab)?.label }} for this site</h2>
          <p class="muted">
            Opening the existing account tool with this environment selected. Full hosting screens will land here next.
          </p>
          <div class="actions">
            <button
              v-if="tab === 'files'"
              type="button"
              class="btn-primary"
              @click="openLegacy('/account/files')"
            >
              Open file manager
            </button>
            <button
              v-else-if="tab === 'databases'"
              type="button"
              class="btn-primary"
              @click="openLegacy('/account/database/studio')"
            >
              Open database studio
            </button>
            <button
              v-else-if="tab === 'domains'"
              type="button"
              class="btn-primary"
              @click="openLegacy('/account', { panel: 'site', tab: 'protect' })"
            >
              Open domain tools
            </button>
            <button
              v-else-if="tab === 'email'"
              type="button"
              class="btn-primary"
              @click="openLegacy('/account', { panel: 'site', tab: 'mail' })"
            >
              Open email tools
            </button>
            <button
              v-else-if="tab === 'transfer'"
              type="button"
              class="btn-primary"
              @click="openLegacy('/account', { panel: 'site', tab: 'ftp' })"
            >
              Open FTP / transfer
            </button>
            <button
              v-else-if="tab === 'apps'"
              type="button"
              class="btn-primary"
              @click="openLegacy('/account', { panel: 'site', tab: 'stack' })"
            >
              Open apps / stacks
            </button>
            <button
              v-else-if="tab === 'backups'"
              type="button"
              class="btn-primary"
              @click="openLegacy('/account', { panel: 'site', tab: 'stack' })"
            >
              Open backups
            </button>
            <button
              v-else
              type="button"
              class="btn-primary"
              @click="openLegacy('/account', { panel: 'site', tab: 'logs' })"
            >
              Open logs
            </button>
          </div>
        </section>
      </template>
    </div>
  </PortalShell>
</template>

<style scoped>
.hosting {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  width: 100%;
  min-width: 0;
}
.top {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: flex-start;
}
.back {
  display: inline-block;
  margin-bottom: 0.35rem;
  color: var(--p-accent);
  font-size: 0.84rem;
  font-weight: 700;
  text-decoration: none;
}
h1 {
  margin: 0;
  font-family: Sora, sans-serif;
  font-size: clamp(1.35rem, 2.2vw, 1.75rem);
  letter-spacing: -0.03em;
  color: var(--p-ink);
}
.lede,
.muted {
  margin: 0.35rem 0 0;
  color: var(--p-muted);
  font-size: 0.9rem;
  line-height: 1.45;
}
.plan-chip {
  margin: 0;
  padding: 0.3rem 0.75rem;
  border-radius: 999px;
  border: 1px solid var(--p-border);
  background: var(--p-surface);
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--p-ink);
}
.tabs {
  display: flex;
  gap: 0.25rem;
  overflow-x: auto;
  padding: 0.28rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--p-border) 55%, var(--p-surface));
  width: fit-content;
  max-width: 100%;
}
.tabs button {
  border: none;
  background: transparent;
  color: var(--p-muted);
  font-size: 0.82rem;
  font-weight: 650;
  padding: 0.45rem 0.9rem;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
}
.tabs button.on {
  background: var(--p-surface);
  color: var(--p-ink);
  box-shadow: 0 1px 2px rgb(22 26 29 / 0.08);
}
.panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.kicker {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-accent);
}
h2 {
  margin: 0.3rem 0 0;
  font-family: Sora, sans-serif;
  font-size: 1.15rem;
  color: var(--p-ink);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 1rem;
}
.btn-primary,
.btn-ghost {
  border-radius: 0.6rem;
  font-size: 0.86rem;
  font-weight: 650;
  padding: 0.55rem 1rem;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}
.btn-primary {
  border: none;
  background: var(--p-accent);
  color: #fff;
}
.btn-ghost {
  border: 1px solid var(--p-border);
  background: transparent;
  color: var(--p-ink);
}
.quick {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem;
}
@media (min-width: 720px) {
  .quick {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
.quick a {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.85rem 0.6rem;
  border: 1px solid var(--p-border);
  border-radius: 0.95rem;
  background: var(--p-surface);
  color: var(--p-ink);
  font-size: 0.84rem;
  font-weight: 650;
  text-decoration: none;
}
</style>
