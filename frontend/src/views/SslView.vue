<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { sslApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { SslCertificate, SslReadinessResponse, SslSummary } from '@/types/hosting'
import type { OperationResult } from '@/types/operations'

const { can } = usePermissions()
const canWrite = computed(() => can(Permission.SSL_WRITE))

const loading = ref(true)
const certs = ref<SslCertificate[]>([])
const summary = ref<SslSummary | null>(null)
const discoveredTotal = ref(0)
const expiringCount = ref(0)
const missingCount = ref(0)
const actionKey = ref<string | null>(null)
const message = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const actionLog = ref<{ title: string; stdout?: string; stderr?: string } | null>(null)

const sslEmail = ref('')
const dryRun = ref(false)
const search = ref('')

const selectedCert = ref<SslCertificate | null>(null)
const readiness = ref<SslReadinessResponse | null>(null)
const webrootOverrides = ref<Record<string, string>>({})

const checkLabels: Record<string, string> = {
  domain_enabled: 'Domain enabled',
  dns_resolves: 'DNS resolves',
  dns_points_here: 'DNS points to server',
  webroot_exists: 'Webroot exists',
  certificate_file_exists: 'Certificate on disk',
  nginx_ssl_block: 'Nginx SSL configured',
  certbot_available: 'Certbot available',
}

const filteredCerts = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return certs.value
  return certs.value.filter(
    (c) =>
      c.domain.includes(q) ||
      c.issuer?.toLowerCase().includes(q) ||
      c.sans.some((s) => s.toLowerCase().includes(q)),
  )
})

async function load() {
  loading.value = true
  try {
    const { data } = await sslApi.list()
    certs.value = data.certificates
    summary.value = data.summary
    discoveredTotal.value = data.discovered_total ?? 0
    expiringCount.value = data.expiring_count ?? 0
    missingCount.value = data.missing_count ?? 0
    for (const cert of data.certificates) {
      if (cert.document_root && !webrootOverrides.value[cert.domain]) {
        webrootOverrides.value[cert.domain] = cert.document_root
      }
    }
  } finally {
    loading.value = false
  }
}

async function openDetail(cert: SslCertificate) {
  selectedCert.value = cert
  readiness.value = null
  actionKey.value = `detail-${cert.domain}`
  try {
    const { data } = await sslApi.get(cert.domain)
    selectedCert.value = data
  } catch (e) {
    message.value = { type: 'err', text: getApiErrorMessage(e, 'Failed to load certificate detail') }
  } finally {
    actionKey.value = null
  }
}

async function checkReadiness(domain: string) {
  actionKey.value = `ready-${domain}`
  readiness.value = null
  try {
    const { data } = await sslApi.readiness(domain)
    readiness.value = data
    if (selectedCert.value?.domain === domain) {
      selectedCert.value = { ...selectedCert.value }
    }
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Readiness check failed' }
  } finally {
    actionKey.value = null
  }
}

function captureLog(title: string, data: OperationResult) {
  const details = data.details as { stdout?: string; stderr?: string }
  actionLog.value = {
    title,
    stdout: details.stdout,
    stderr: details.stderr,
  }
}

async function runAction(action: 'issue' | 'renew' | 'reissue', cert: SslCertificate) {
  actionKey.value = `${action}-${cert.domain}`
  message.value = null
  try {
    const fn = action === 'issue' ? sslApi.issue : action === 'renew' ? sslApi.renew : sslApi.reissue
    const { data } = await fn({
      domain: cert.domain,
      email: sslEmail.value || undefined,
      webroot: webrootOverrides.value[cert.domain] || cert.document_root || undefined,
      dry_run: dryRun.value,
    })
    message.value = { type: data.success ? 'ok' : 'err', text: data.message }
    captureLog(`${action} ${cert.domain}`, data)
    await load()
    if (selectedCert.value?.domain === cert.domain) {
      const { data: detail } = await sslApi.get(cert.domain)
      selectedCert.value = detail
    }
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'SSL action failed' }
  } finally {
    actionKey.value = null
  }
}

async function renewAll() {
  actionKey.value = 'renew-all'
  message.value = null
  try {
    const { data } = await sslApi.renewAll(dryRun.value, sslEmail.value || undefined)
    message.value = { type: data.success ? 'ok' : 'err', text: data.message }
    captureLog('Renew all certificates', data)
    await load()
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Renew all failed' }
  } finally {
    actionKey.value = null
  }
}

function statusVariant(cert: SslCertificate) {
  if (!cert.configured) return 'neutral' as const
  if (cert.status === 'unhealthy' || (cert.days_remaining ?? 0) < 0) return 'danger' as const
  if (cert.status === 'degraded' || (cert.days_remaining ?? 99) < 14) return 'warning' as const
  return 'success' as const
}

function statusLabel(cert: SslCertificate) {
  if (!cert.configured) return 'Not configured'
  if ((cert.days_remaining ?? 0) < 0) return 'Expired'
  if ((cert.days_remaining ?? 99) < 14) return `${cert.days_remaining}d left`
  return `${cert.days_remaining ?? '?'}d left`
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

onMounted(load)
</script>

<template>
  <DashboardLayout @refresh="load">
    <div class="animate-fade-in space-y-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-lg font-semibold text-slate-900 dark:text-white">SSL Certificates</h1>
          <p class="text-sm text-surface-muted">
            IFNOTUS-managed and VPS-discovered certificates
            <span v-if="discoveredTotal"> · {{ discoveredTotal }} discovered</span>
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <RouterLink
            to="/domains"
            class="rounded-lg border border-surface-border px-3 py-2 text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
          >
            Manage domains
          </RouterLink>
          <button
            type="button"
            class="rounded-lg border border-surface-border px-3 py-2 text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
            :disabled="loading"
            @click="load"
          >
            Refresh
          </button>
          <button
            v-if="canWrite"
            type="button"
            class="rounded-lg bg-brand-600 px-3 py-2 text-sm text-white hover:bg-brand-700 disabled:opacity-50"
            :disabled="!!actionKey"
            @click="renewAll"
          >
            Renew all
          </button>
        </div>
      </div>

      <section v-if="summary" class="dashboard-grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8">
        <Card padding="sm"><p class="text-xs text-surface-muted">Total</p><p class="text-xl font-semibold">{{ summary.total }}</p></Card>
        <Card padding="sm"><p class="text-xs text-surface-muted">Configured</p><p class="text-xl font-semibold">{{ summary.configured }}</p></Card>
        <Card padding="sm"><p class="text-xs text-surface-muted">Healthy</p><p class="text-xl font-semibold text-emerald-600">{{ summary.healthy }}</p></Card>
        <Card padding="sm"><p class="text-xs text-surface-muted">Discovered</p><p class="text-xl font-semibold text-sky-600">{{ discoveredTotal }}</p></Card>
        <Card padding="sm"><p class="text-xs text-surface-muted">Expiring</p><p class="text-xl font-semibold text-amber-600">{{ expiringCount || summary.expiring_soon }}</p></Card>
        <Card padding="sm"><p class="text-xs text-surface-muted">Expired</p><p class="text-xl font-semibold text-red-600">{{ summary.expired }}</p></Card>
        <Card padding="sm"><p class="text-xs text-surface-muted">Missing</p><p class="text-xl font-semibold">{{ missingCount || summary.missing }}</p></Card>
      </section>

      <Card padding="md">
        <div class="grid gap-3 md:grid-cols-3">
          <label class="block text-sm md:col-span-2">
            <span class="text-surface-muted">Search domains, issuer, or SAN</span>
            <input v-model="search" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" placeholder="example.com" />
          </label>
          <label class="block text-sm">
            <span class="text-surface-muted">Certbot email</span>
            <input v-model="sslEmail" type="email" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" placeholder="admin@example.com" />
          </label>
        </div>
        <label v-if="canWrite" class="mt-3 flex items-center gap-2 text-sm text-surface-muted">
          <input v-model="dryRun" type="checkbox" class="rounded border-surface-border" />
          Dry run (simulate certbot without changing certificates)
        </label>
      </Card>

      <p
        v-if="message"
        class="rounded-lg px-3 py-2 text-sm"
        :class="message.type === 'ok' ? 'bg-emerald-500/10 text-emerald-700' : 'bg-red-500/10 text-red-700'"
      >
        {{ message.text }}
      </p>

      <Card v-if="actionLog" padding="md">
        <div class="mb-2 flex items-center justify-between">
          <h2 class="text-sm font-semibold">Certbot output — {{ actionLog.title }}</h2>
          <button type="button" class="text-xs text-surface-muted underline" @click="actionLog = null">Dismiss</button>
        </div>
        <pre v-if="actionLog.stdout" class="max-h-48 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{{ actionLog.stdout }}</pre>
        <pre v-if="actionLog.stderr" class="mt-2 max-h-32 overflow-auto rounded-lg bg-red-950/30 p-3 text-xs text-red-200">{{ actionLog.stderr }}</pre>
      </Card>

      <div v-if="loading" class="text-sm text-surface-muted">Loading certificates…</div>
      <div v-else-if="!certs.length" class="rounded-xl border border-dashed border-surface-border p-8 text-center text-sm text-surface-muted">
        No domains registered. <RouterLink to="/domains" class="text-brand-600 underline">Add domains</RouterLink> first.
      </div>

      <div v-else class="grid gap-4 lg:grid-cols-5">
        <div class="space-y-2 lg:col-span-2">
          <div
            v-for="cert in filteredCerts"
            :key="cert.domain"
            class="cursor-pointer rounded-xl border px-4 py-3 transition"
            :class="
              selectedCert?.domain === cert.domain
                ? 'border-brand-500 bg-brand-500/5'
                : 'border-surface-border bg-surface-raised hover:border-brand-500/30'
            "
            @click="openDetail(cert)"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-slate-900 dark:text-white">{{ cert.domain }}</span>
              <div class="flex gap-1">
                <Badge v-if="cert.reconciliation_state" size="sm" variant="info">
                  {{ cert.reconciliation_state }}
                </Badge>
                <Badge :variant="statusVariant(cert)" size="sm">{{ statusLabel(cert) }}</Badge>
              </div>
            </div>
            <p v-if="cert.issuer" class="mt-1 truncate text-xs text-surface-muted">{{ cert.issuer }}</p>
          </div>
        </div>

        <div class="lg:col-span-3">
          <Card v-if="!selectedCert" padding="md">
            <p class="text-sm text-surface-muted">Select a domain to inspect certificate details and run actions.</p>
          </Card>

          <div v-else class="space-y-4">
            <Card padding="md">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 class="text-base font-semibold">{{ selectedCert.domain }}</h2>
                  <div class="mt-2 flex flex-wrap gap-2">
                    <Badge :variant="statusVariant(selectedCert)" size="sm">{{ selectedCert.status ?? 'unknown' }}</Badge>
                    <Badge :variant="selectedCert.domain_enabled ? 'success' : 'neutral'" size="sm">
                      {{ selectedCert.domain_enabled ? 'Domain on' : 'Domain off' }}
                    </Badge>
                    <Badge :variant="selectedCert.nginx_ssl_enabled ? 'info' : 'warning'" size="sm">
                      nginx SSL {{ selectedCert.nginx_ssl_enabled ? 'on' : 'off' }}
                    </Badge>
                  </div>
                </div>
                <button
                  type="button"
                  class="rounded-lg border border-surface-border px-2.5 py-1.5 text-xs"
                  :disabled="!!actionKey"
                  @click="checkReadiness(selectedCert.domain)"
                >
                  Validate readiness
                </button>
              </div>

              <dl class="mt-4 grid gap-2 text-sm md:grid-cols-2">
                <div><dt class="text-surface-muted">Subject</dt><dd class="font-mono text-xs">{{ selectedCert.subject ?? '—' }}</dd></div>
                <div><dt class="text-surface-muted">Issuer</dt><dd class="text-xs">{{ selectedCert.issuer ?? '—' }}</dd></div>
                <div><dt class="text-surface-muted">Valid from</dt><dd>{{ formatDate(selectedCert.valid_from) }}</dd></div>
                <div><dt class="text-surface-muted">Valid until</dt><dd>{{ formatDate(selectedCert.valid_until) }}</dd></div>
                <div><dt class="text-surface-muted">Days remaining</dt><dd>{{ selectedCert.days_remaining ?? '—' }}</dd></div>
                <div><dt class="text-surface-muted">Fingerprint (SHA256)</dt><dd class="break-all font-mono text-[10px]">{{ selectedCert.fingerprint_sha256 ?? '—' }}</dd></div>
                <div class="md:col-span-2"><dt class="text-surface-muted">SANs</dt><dd>{{ selectedCert.sans?.length ? selectedCert.sans.join(', ') : '—' }}</dd></div>
                <div class="md:col-span-2"><dt class="text-surface-muted">Certificate</dt><dd class="font-mono text-xs">{{ selectedCert.certificate_path ?? '—' }}</dd></div>
                <div class="md:col-span-2"><dt class="text-surface-muted">Private key</dt><dd class="font-mono text-xs">{{ selectedCert.private_key_path ?? '—' }}</dd></div>
                <div class="md:col-span-2"><dt class="text-surface-muted">Document root</dt><dd class="font-mono text-xs">{{ selectedCert.document_root ?? '—' }}</dd></div>
              </dl>
              <p v-if="selectedCert.message" class="mt-3 text-xs text-amber-600">{{ selectedCert.message }}</p>
            </Card>

            <Card v-if="readiness && readiness.domain === selectedCert.domain" padding="md">
              <h3 class="text-sm font-semibold">Issuance readiness</h3>
              <p class="mt-1 text-xs" :class="readiness.ready ? 'text-emerald-600' : 'text-amber-600'">
                {{ readiness.ready ? 'Ready for Let\'s Encrypt issuance' : 'Not ready — resolve checks below' }}
              </p>
              <div class="mt-3 grid gap-2 sm:grid-cols-2">
                <div
                  v-for="(passed, key) in readiness.checks"
                  :key="key"
                  class="flex items-center justify-between rounded-lg border border-surface-border px-3 py-2 text-xs"
                >
                  <span>{{ checkLabels[key] ?? key }}</span>
                  <Badge :variant="passed ? 'success' : 'danger'" size="sm">{{ passed ? 'Pass' : 'Fail' }}</Badge>
                </div>
              </div>
              <ul v-if="readiness.messages.length" class="mt-3 list-inside list-disc text-xs text-surface-muted">
                <li v-for="(m, i) in readiness.messages" :key="i">{{ m }}</li>
              </ul>
            </Card>

            <Card v-if="canWrite" padding="md">
              <h3 class="mb-3 text-sm font-semibold">Certificate actions</h3>
              <label class="block text-sm">
                <span class="text-surface-muted">Webroot override</span>
                <input
                  v-model="webrootOverrides[selectedCert.domain]"
                  class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-xs"
                  placeholder="/var/www/example"
                />
              </label>
              <div class="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  class="rounded-lg bg-brand-600 px-3 py-2 text-sm text-white disabled:opacity-50"
                  :disabled="!!actionKey"
                  @click="runAction('issue', selectedCert)"
                >
                  Issue
                </button>
                <button
                  type="button"
                  class="rounded-lg border border-surface-border px-3 py-2 text-sm disabled:opacity-50"
                  :disabled="!!actionKey"
                  @click="runAction('renew', selectedCert)"
                >
                  Renew
                </button>
                <button
                  type="button"
                  class="rounded-lg border border-surface-border px-3 py-2 text-sm disabled:opacity-50"
                  :disabled="!!actionKey"
                  @click="runAction('reissue', selectedCert)"
                >
                  Reissue
                </button>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  </DashboardLayout>
</template>
