<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { sslApi } from '@/api'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { SslCertificate, SslReadinessResponse } from '@/types/hosting'

const { can } = usePermissions()
const canWrite = computed(() => can(Permission.SSL_WRITE))

const loading = ref(true)
const certs = ref<SslCertificate[]>([])
const actionKey = ref<string | null>(null)
const message = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const readiness = ref<SslReadinessResponse | null>(null)
const selectedDomain = ref('')
const sslEmail = ref('')
const dryRun = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await sslApi.list()
    certs.value = data.certificates
  } finally {
    loading.value = false
  }
}

async function runAction(action: 'issue' | 'renew' | 'reissue', domain: string) {
  actionKey.value = `${action}-${domain}`
  message.value = null
  try {
    const fn = action === 'issue' ? sslApi.issue : action === 'renew' ? sslApi.renew : sslApi.reissue
    const { data } = await fn({ domain, email: sslEmail.value || undefined, dry_run: dryRun.value })
    message.value = { type: data.success ? 'ok' : 'err', text: data.message }
    await load()
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'SSL action failed' }
  } finally {
    actionKey.value = null
  }
}

async function checkReadiness(domain: string) {
  selectedDomain.value = domain
  actionKey.value = `ready-${domain}`
  readiness.value = null
  try {
    const { data } = await sslApi.readiness(domain)
    readiness.value = data
  } catch (e) {
    message.value = { type: 'err', text: e instanceof Error ? e.message : 'Readiness check failed' }
  } finally {
    actionKey.value = null
  }
}

function statusVariant(cert: SslCertificate) {
  if (!cert.configured) return 'neutral' as const
  if ((cert.days_remaining ?? 0) < 14) return 'warning' as const
  return 'success' as const
}

onMounted(load)
</script>

<template>
  <DashboardLayout @refresh="load">
    <div class="animate-fade-in space-y-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-lg font-semibold text-slate-900 dark:text-white">SSL Certificates</h1>
          <p class="text-sm text-surface-muted">Let's Encrypt issuance, renewal, and inspection</p>
        </div>
        <button
          type="button"
          class="rounded-lg border border-surface-border px-3 py-2 text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
          :disabled="loading"
          @click="load"
        >
          Refresh
        </button>
      </div>

      <label class="block max-w-md text-sm">
        <span class="text-surface-muted">Contact email for certbot (optional)</span>
        <input v-model="sslEmail" type="email" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2" placeholder="admin@example.com" />
      </label>
      <label v-if="canWrite" class="flex items-center gap-2 text-sm text-surface-muted">
        <input v-model="dryRun" type="checkbox" class="rounded border-surface-border" />
        Dry run (test without issuing)
      </label>

      <p
        v-if="message"
        class="rounded-lg px-3 py-2 text-sm"
        :class="message.type === 'ok' ? 'bg-emerald-500/10 text-emerald-700' : 'bg-red-500/10 text-red-700'"
      >
        {{ message.text }}
      </p>

      <Card v-if="readiness && selectedDomain" padding="sm">
        <p class="text-sm font-medium">Readiness: {{ readiness.domain }}</p>
        <p class="text-xs" :class="readiness.ready ? 'text-emerald-600' : 'text-amber-600'">
          {{ readiness.ready ? 'Ready for issuance' : 'Not ready' }}
        </p>
        <ul v-if="readiness.messages.length" class="mt-2 list-inside list-disc text-xs text-surface-muted">
          <li v-for="(m, i) in readiness.messages" :key="i">{{ m }}</li>
        </ul>
      </Card>

      <div v-if="loading" class="text-sm text-surface-muted">Loading certificates…</div>
      <div v-else-if="!certs.length" class="rounded-xl border border-dashed border-surface-border p-8 text-center text-sm text-surface-muted">
        No domains registered. Add domains first to manage SSL.
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="cert in certs"
          :key="cert.domain"
          class="rounded-xl border border-surface-border bg-surface-raised px-4 py-3"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium">{{ cert.domain }}</span>
                <Badge :variant="statusVariant(cert)" size="sm">
                  {{ cert.configured ? `${cert.days_remaining ?? '?'}d left` : 'Not configured' }}
                </Badge>
              </div>
              <p v-if="cert.issuer" class="mt-1 text-xs text-surface-muted">Issuer: {{ cert.issuer }}</p>
              <p v-if="cert.valid_until" class="text-xs text-surface-muted">Expires: {{ cert.valid_until }}</p>
              <p v-if="cert.certificate_path" class="text-xs text-surface-muted">{{ cert.certificate_path }}</p>
              <p v-if="cert.sans?.length" class="text-xs text-surface-muted">SANs: {{ cert.sans.join(', ') }}</p>
            </div>
            <div v-if="canWrite" class="flex flex-wrap gap-2">
              <button type="button" class="rounded-lg border border-surface-border px-2.5 py-1.5 text-xs" :disabled="!!actionKey" @click="checkReadiness(cert.domain)">
                Validate
              </button>
              <button type="button" class="rounded-lg border border-surface-border px-2.5 py-1.5 text-xs" :disabled="!!actionKey" @click="runAction('issue', cert.domain)">
                Issue
              </button>
              <button type="button" class="rounded-lg border border-surface-border px-2.5 py-1.5 text-xs" :disabled="!!actionKey" @click="runAction('renew', cert.domain)">
                Renew
              </button>
              <button type="button" class="rounded-lg border border-surface-border px-2.5 py-1.5 text-xs" :disabled="!!actionKey" @click="runAction('reissue', cert.domain)">
                Reissue
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </DashboardLayout>
</template>
