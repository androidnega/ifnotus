<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { healthApi, aiApi, mailApi, platformAdminApi } from '@/api'
import { REALTIME_POLL_MS } from '@/config/polling'
import { useAuthStore } from '@/stores/auth'
import { usePolling } from '@/composables/usePolling'
import { Permission } from '@/lib/permissions'
import { usePermissions } from '@/composables/usePermissions'
import { isPlatformOwner, isPlatformAdmin, isStaffUser } from '@/lib/roles'
import Skeleton from '@/components/ui/Skeleton.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import UiTabBar from '@/components/ui/UiTabBar.vue'
import { getApiErrorMessage } from '@/lib/apiError'
import { useSiteTheme } from '@/composables/useSiteTheme'
import { useThemeStore } from '@/stores/theme'
import type { ReadinessResponse } from '@/types/dashboard'
import type { AiSettings } from '@/types/ai'
import type { IntegrationsStatus } from '@/types/integrations'

interface WebmailSettings {
  support_whatsapp: string
  support_url: string
  product_name: string
  auto_detect_domains: boolean
  updated_at?: string | null
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { can } = usePermissions()
const isOwner = computed(() => isPlatformOwner(auth.user))
const isAdmin = computed(() => isPlatformAdmin(auth.user))
const isStaff = computed(() => isStaffUser(auth.user))

const canManageSecurity = computed(() => isOwner.value || isAdmin.value || can(Permission.SYSTEM_ADMIN) || isStaff.value)

const { data: readiness, refresh: refreshReadiness } = usePolling<ReadinessResponse>(
  async () => (await healthApi.readiness()).data,
  REALTIME_POLL_MS,
)

const aiSettings = ref<AiSettings | null>(null)
const aiLoading = ref(false)
const aiSaving = ref(false)
const aiKey = ref('')
const aiModel = ref('deepseek-chat')
const aiAgentName = ref('SNR Dev')
const aiMessage = ref<{ ok: boolean; text: string } | null>(null)
const settingsTab = ref('account')
const canManageAi = computed(() => isOwner.value || isAdmin.value || can(Permission.SYSTEM_ADMIN) || can(Permission.PLATFORM_WRITE) || isStaff.value)

const webmailSettings = ref<WebmailSettings | null>(null)
const webmailLoading = ref(false)
const webmailSaving = ref(false)
const webmailWhatsapp = ref('+233541069241')
const webmailProduct = ref('IFNOTUS Webmail')
const webmailAutoDetect = ref(true)
const webmailMessage = ref<{ ok: boolean; text: string } | null>(null)
const canManageWebmail = computed(() => isOwner.value || isAdmin.value || can(Permission.SYSTEM_ADMIN) || can(Permission.PLATFORM_WRITE) || isStaff.value)
const canManageIntegrations = computed(() => isOwner.value || isAdmin.value || can(Permission.PLATFORM_WRITE) || can(Permission.SYSTEM_ADMIN) || isStaff.value)
const canManageTheme = computed(() => isOwner.value || isAdmin.value || can(Permission.PLATFORM_WRITE) || isStaff.value)
const canManageStaff = computed(
  () => (isOwner.value || isAdmin.value || can(Permission.USERS_WRITE) || can(Permission.SYSTEM_ADMIN) || isStaff.value) && !auth.user?.privilege_viewing_as,
)

const siteTheme = ref('studio-light')
const siteThemes = ref<Array<{ id: string; name: string; description: string; colors?: Record<string, string> }>>([])
const homeLayout = ref('split-right')
const homeLayouts = ref<Array<{ id: string; name: string; description: string }>>([])
const maintenanceMode = ref(false)
const maintenanceMessage = ref('')
const siteThemeLoading = ref(false)
const siteThemeSaving = ref(false)
const siteThemeMessage = ref<{ ok: boolean; text: string } | null>(null)
const siteColors = ref({
  primary: '#ff6c2c',
  primary_hover: '#e85a1c',
  ink: '#161a1d',
  paper: '#f8fafc',
  surface: '#ffffff',
  muted: '#6b7280',
  border: '#e7e2db',
})
const planColorEdits = ref<Array<{ id: string; label: string; max_price: string | number; accent: string }>>([])

const apiIntegrations = ref<IntegrationsStatus | null>(null)
const apiIntLoading = ref(false)
const apiIntSaving = ref(false)
const apiIntMessage = ref<{ ok: boolean; text: string } | null>(null)

const ncUser = ref('')
const ncKey = ref('')
const ncIp = ref('80.241.223.82')
const psPublic = ref('')
const psSecret = ref('')
const smtpHost = ref('')
const smtpPort = ref(587)
const smtpUser = ref('')
const smtpPass = ref('')
const smtpFrom = ref('')
const smtpTls = ref(true)
const smsProvider = ref('none')
const smsKey = ref('')
const smsSecret = ref('')
const smsFallbackKey = ref('')
const smsSender = ref('IFNOTUS')
const momoNetwork = ref('MTN')
const momoNumber = ref('0257940791')
const momoAccount = ref('Emmanuel Kwofie')
const staffEmail = ref('')
const staffName = ref('')
const staffPassword = ref('')
const staffRole = ref('operator')
const staffMsg = ref('')
const staffList = ref<
  Array<{
    id: string
    email: string
    username: string
    full_name?: string | null
    roles: string[]
    is_active: boolean
    is_superuser: boolean
    last_login_at?: string | null
  }>
>([])
const staffLoading = ref(false)

const roleLabels: Record<string, string> = {
  admin: 'Business admin — plans, orders, customers, env remediation',
  operator: 'Hosting operator — domains, mail, files, databases, env ops',
  viewer: 'Viewer — read only',
  customer_care: 'Customer care — MoMo confirm & support tickets',
  superadmin: 'Super admin — staff accounts, terminal, terminate',
}


const settingsTabs = computed(() => {
  const tabs = [{ id: 'account', label: 'Account' }]
  if (canManageTheme.value) tabs.push({ id: 'theme', label: 'Theme' })
  if (canManageIntegrations.value) tabs.push({ id: 'integrations', label: 'Integrations' })
  if (canManageAi.value) tabs.push({ id: 'ai', label: 'AI agent' })
  if (canManageWebmail.value) tabs.push({ id: 'webmail', label: 'Webmail' })
  if (canManageStaff.value) tabs.push({ id: 'staff', label: 'Staff' })
  if (isOwner.value || isAdmin.value || can(Permission.SYSTEM_ADMIN) || can(Permission.PLATFORM_READ) || isStaff.value) {
    tabs.push({ id: 'health', label: 'Health' })
  }
  return tabs
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

async function loadAiSettings() {
  if (!canManageAi.value) return
  aiLoading.value = true
  aiMessage.value = null
  try {
    const { data } = await aiApi.getSettings()
    aiSettings.value = data
    aiModel.value = data.model || 'deepseek-chat'
    aiAgentName.value = data.agent_name || 'SNR Dev'
  } catch (e) {
    aiMessage.value = { ok: false, text: getApiErrorMessage(e, 'Failed to load AI settings') }
  } finally {
    aiLoading.value = false
  }
}

async function saveAiSettings() {
  aiSaving.value = true
  aiMessage.value = null
  try {
    const body: { api_key?: string; model?: string; agent_name?: string; clear?: boolean } = {
      model: aiModel.value.trim() || 'deepseek-chat',
      agent_name: aiAgentName.value.trim() || 'SNR Dev',
    }
    if (aiKey.value.trim()) body.api_key = aiKey.value.trim()
    const { data } = await aiApi.updateSettings(body)
    aiSettings.value = data
    aiAgentName.value = data.agent_name || aiAgentName.value
    aiKey.value = ''
    aiMessage.value = { ok: true, text: 'AI agent settings saved.' }
  } catch (e) {
    aiMessage.value = { ok: false, text: getApiErrorMessage(e, 'Failed to save AI settings') }
  } finally {
    aiSaving.value = false
  }
}

async function clearAiKey() {
  if (!confirm('Remove the stored AI agent API key?')) return
  aiSaving.value = true
  try {
    const { data } = await aiApi.updateSettings({ clear: true })
    aiSettings.value = data
    aiKey.value = ''
    aiMessage.value = { ok: true, text: 'API key cleared.' }
  } catch (e) {
    aiMessage.value = { ok: false, text: getApiErrorMessage(e, 'Failed to clear API key') }
  } finally {
    aiSaving.value = false
  }
}

async function loadWebmailSettings() {
  if (!canManageWebmail.value) return
  webmailLoading.value = true
  webmailMessage.value = null
  try {
    const { data } = await mailApi.getSettings()
    webmailSettings.value = data
    webmailWhatsapp.value = data.support_whatsapp || '+233541069241'
    webmailProduct.value = data.product_name || 'IFNOTUS Webmail'
    webmailAutoDetect.value = data.auto_detect_domains !== false
  } catch (e) {
    webmailMessage.value = { ok: false, text: getApiErrorMessage(e, 'Failed to load webmail settings') }
  } finally {
    webmailLoading.value = false
  }
}

async function saveWebmailSettings() {
  webmailSaving.value = true
  webmailMessage.value = null
  try {
    const { data } = await mailApi.updateSettings({
      support_whatsapp: webmailWhatsapp.value.trim(),
      product_name: webmailProduct.value.trim() || 'IFNOTUS Webmail',
      auto_detect_domains: webmailAutoDetect.value,
    })
    webmailSettings.value = data
    webmailMessage.value = {
      ok: true,
      text: `Saved. Support opens WhatsApp: ${data.support_url}`,
    }
  } catch (e) {
    webmailMessage.value = { ok: false, text: getApiErrorMessage(e, 'Failed to save webmail settings') }
  } finally {
    webmailSaving.value = false
  }
}

async function syncWebmailDomains() {
  webmailSaving.value = true
  webmailMessage.value = null
  try {
    const { data } = await mailApi.syncDomains()
    webmailMessage.value = {
      ok: data.success,
      text: data.message || 'Webmail domain sync finished.',
    }
  } catch (e) {
    webmailMessage.value = { ok: false, text: getApiErrorMessage(e, 'Domain sync failed') }
  } finally {
    webmailSaving.value = false
  }
}

async function loadSiteTheme() {
  if (!canManageIntegrations.value) return
  siteThemeLoading.value = true
  siteThemeMessage.value = null
  try {
    const { data } = await platformAdminApi.getSiteTheme()
    siteTheme.value = data.theme || 'studio-light'
    siteThemes.value = data.themes || []
    homeLayout.value = data.home_layout || 'split-right'
    homeLayouts.value = data.home_layouts || []
    maintenanceMode.value = Boolean(data.maintenance_mode)
    maintenanceMessage.value = data.maintenance_message || ''
    if (data.colors) siteColors.value = { ...siteColors.value, ...data.colors }
    planColorEdits.value = data.plan_colors || []
  } catch (e) {
    siteThemeMessage.value = {
      ok: false,
      text: getApiErrorMessage(e, 'Failed to load website theme'),
    }
  } finally {
    siteThemeLoading.value = false
  }
}

async function saveSiteTheme() {
  siteThemeSaving.value = true
  siteThemeMessage.value = null
  try {
    const planMap: Record<string, string> = {}
    for (const row of planColorEdits.value) planMap[row.id] = row.accent
    const { data } = await platformAdminApi.updateSiteTheme({
      theme: siteTheme.value,
      colors: siteColors.value,
      plan_colors: planMap,
      home_layout: homeLayout.value,
      maintenance_mode: maintenanceMode.value,
      maintenance_message: maintenanceMessage.value,
    })
    siteTheme.value = data.theme
    siteThemes.value = data.themes || []
    homeLayout.value = data.home_layout || homeLayout.value
    homeLayouts.value = data.home_layouts || homeLayouts.value
    maintenanceMode.value = Boolean(data.maintenance_mode)
    maintenanceMessage.value = data.maintenance_message || maintenanceMessage.value
    if (data.colors) siteColors.value = { ...siteColors.value, ...data.colors }
    planColorEdits.value = data.plan_colors || []
    // Live-apply for this browser
    const { applyThemeColors } = await import('@/lib/theme')
    applyThemeColors(siteColors.value, document.documentElement, data.theme)
    const site = useSiteTheme()
    site.theme.value = data.theme
    site.applyLocal(siteColors.value)
    useThemeStore().setMode('light')
    siteThemeMessage.value = {
      ok: true,
      text: 'Theme and colors saved. Portal and panels will use the new palette.',
    }
  } catch (e) {
    siteThemeMessage.value = {
      ok: false,
      text: getApiErrorMessage(e, 'Failed to save website theme'),
    }
  } finally {
    siteThemeSaving.value = false
  }
}

function applyPresetColors(opt: { id: string; colors?: Record<string, string> }) {
  siteTheme.value = opt.id
  if (opt.colors) siteColors.value = { ...siteColors.value, ...opt.colors }
  void import('@/lib/theme').then(({ applyThemeColors }) =>
    applyThemeColors(siteColors.value, document.documentElement, opt.id),
  )
  const site = useSiteTheme()
  site.theme.value = opt.id
  if (opt.colors) site.applyLocal(opt.colors)
  useThemeStore().setMode('light')
}

watch(
  siteColors,
  (colors) => {
    void import('@/lib/theme').then(({ applyThemeColors }) => applyThemeColors(colors))
  },
  { deep: true },
)

const smsBalanceData = ref<{
  ok: boolean
  provider: string
  sms_balance?: number | null
  main_balance?: number | null
  total_sms_sent?: number
  estimated_spent_ghs?: number
  unit_rate_ghs?: number
  message?: string
} | null>(null)
const smsBalanceLoading = ref(false)

const domainPrices = ref<Record<string, number>>({
  '.online': 65,
  '.com': 225,
  '.org': 240,
  '.net': 260,
  '.xyz': 70,
  '.store': 95,
  '.tech': 120,
  '.site': 65,
  '.me': 150,
  '.info': 190,
})

async function loadSmsBalance() {
  smsBalanceLoading.value = true
  try {
    const { data } = await platformAdminApi.getSmsBalance()
    smsBalanceData.value = data
  } catch (e) {
    smsBalanceData.value = {
      ok: false,
      provider: smsProvider.value,
      message: getApiErrorMessage(e, 'Could not fetch live SMS balance.'),
    }
  } finally {
    smsBalanceLoading.value = false
  }
}

async function loadApiIntegrations() {
  if (!canManageIntegrations.value) return
  apiIntLoading.value = true
  apiIntMessage.value = null
  try {
    const { data } = await platformAdminApi.getIntegrations()
    apiIntegrations.value = data
    ncUser.value = data.namecheap.api_user || ''
    ncIp.value = data.namecheap.client_ip || '80.241.223.82'
    ncKey.value = ''
    psPublic.value = data.paystack.public_key || ''
    psSecret.value = ''
    smtpHost.value = data.smtp.host || ''
    smtpPort.value = data.smtp.port || 587
    smtpUser.value = data.smtp.username || ''
    smtpPass.value = ''
    smtpFrom.value = data.smtp.from_address || ''
    smtpTls.value = data.smtp.use_tls !== false
    smsProvider.value = data.sms.provider || 'none'
    smsKey.value = ''
    smsSecret.value = ''
    smsFallbackKey.value = ''
    smsSender.value = data.sms.sender_id || 'IFNOTUS'
    momoNetwork.value = data.momo?.network || 'MTN'
    momoNumber.value = data.momo?.number || '0257940791'
    momoAccount.value = data.momo?.account_name || 'Emmanuel Kwofie'
    if (data.domain_prices && Object.keys(data.domain_prices).length > 0) {
      domainPrices.value = { ...domainPrices.value, ...data.domain_prices }
    }
    if (data.sms.configured && smsProvider.value !== 'none') {
      void loadSmsBalance()
    }
  } catch (e) {
    apiIntMessage.value = {
      ok: false,
      text: getApiErrorMessage(e, 'Failed to load API integrations'),
    }
  } finally {
    apiIntLoading.value = false
  }
}

async function saveApiIntegrations() {
  apiIntSaving.value = true
  apiIntMessage.value = null
  try {
    const body: import('@/types/integrations').IntegrationsUpdatePayload = {
      namecheap: {
        api_user: ncUser.value.trim() || null,
        client_ip: ncIp.value.trim() || null,
      },
      paystack: {
        public_key: psPublic.value.trim() || null,
      },
      smtp: {
        host: smtpHost.value.trim() || null,
        port: smtpPort.value,
        username: smtpUser.value.trim() || null,
        from_address: smtpFrom.value.trim() || null,
        use_tls: smtpTls.value,
      },
      sms: {
        provider: smsProvider.value.trim() || 'none',
        sender_id: smsSender.value.trim() || 'IFNOTUS',
        fallback_provider: 'moolre',
      },
      momo: {
        network: momoNetwork.value.trim() || 'MTN',
        number: momoNumber.value.trim() || null,
        account_name: momoAccount.value.trim() || 'Emmanuel Kwofie',
      },
      domain_prices: domainPrices.value,
    }
    if (ncKey.value.trim()) body.namecheap!.api_key = ncKey.value.trim()
    if (psSecret.value.trim()) body.paystack!.secret_key = psSecret.value.trim()
    if (smtpPass.value.trim()) body.smtp!.password = smtpPass.value.trim()
    if (smsKey.value.trim()) body.sms!.api_key = smsKey.value.trim()
    if (smsSecret.value.trim()) body.sms!.api_secret = smsSecret.value.trim()
    if (smsFallbackKey.value.trim()) body.sms!.fallback_api_key = smsFallbackKey.value.trim()

    const { data } = await platformAdminApi.updateIntegrations(body)
    apiIntegrations.value = data
    ncKey.value = ''
    psSecret.value = ''
    smtpPass.value = ''
    smsKey.value = ''
    smsSecret.value = ''
    smsFallbackKey.value = ''
    apiIntMessage.value = {
      ok: true,
      text: 'API integrations saved. Keys are stored encrypted on the server — no code edit needed.',
    }
    if (smsProvider.value !== 'none') {
      void loadSmsBalance()
    }
  } catch (e) {
    apiIntMessage.value = {
      ok: false,
      text: getApiErrorMessage(e, 'Failed to save API integrations'),
    }
  } finally {
    apiIntSaving.value = false
  }
}

async function importApiIntegrationsFromEnv() {
  if (!confirm('Import current server .env Namecheap / Paystack / SMTP / SMS values into Settings?')) {
    return
  }
  apiIntSaving.value = true
  try {
    const { data } = await platformAdminApi.importIntegrationsFromEnv()
    apiIntegrations.value = data
    await loadApiIntegrations()
    apiIntMessage.value = { ok: true, text: 'Imported from server environment into Settings store.' }
    if (smsProvider.value !== 'none') {
      void loadSmsBalance()
    }
  } catch (e) {
    apiIntMessage.value = {
      ok: false,
      text: getApiErrorMessage(e, 'Import failed'),
    }
  } finally {
    apiIntSaving.value = false
  }
}

async function loadStaffUsers() {
  if (!canManageStaff.value) {
    staffList.value = []
    return
  }
  staffLoading.value = true
  try {
    const { data } = await platformAdminApi.listStaffUsers()
    staffList.value = data
  } catch {
    staffList.value = []
  } finally {
    staffLoading.value = false
  }
}

async function createStaffUser() {
  staffMsg.value = ''
  try {
    await platformAdminApi.createStaffUser({
      email: staffEmail.value.trim(),
      password: staffPassword.value,
      full_name: staffName.value.trim(),
      role: staffRole.value,
    })
    staffMsg.value =
      staffRole.value === 'operator'
        ? 'Hosting operator created. They can manage DNS, mail, files, databases, and env remediation.'
        : staffRole.value === 'admin'
          ? 'Business admin created. They can manage plans, orders, customers, and env remediation.'
          : staffRole.value === 'customer_care'
            ? 'Customer care created. They can confirm MoMo and handle support tickets.'
            : 'Staff account created and activated. They can sign in at https://fpanel.ifnotus.space.'
    staffPassword.value = ''
    staffEmail.value = ''
    staffName.value = ''
    await loadStaffUsers()
  } catch (e) {
    staffMsg.value = getApiErrorMessage(e, 'Could not create staff user.')
  }
}

async function setStaffActive(id: string, active: boolean) {
  staffMsg.value = ''
  try {
    await platformAdminApi.updateStaffUser(id, { is_active: active })
    staffMsg.value = active ? 'Staff account activated.' : 'Staff account deactivated.'
    await loadStaffUsers()
  } catch (e) {
    staffMsg.value = getApiErrorMessage(e, 'Could not update staff user.')
  }
}

async function setStaffRole(id: string, role: string) {
  staffMsg.value = ''
  try {
    await platformAdminApi.updateStaffUser(id, { role })
    staffMsg.value = `Role updated to ${roleLabels[role] || role}.`
    await loadStaffUsers()
  } catch (e) {
    staffMsg.value = getApiErrorMessage(e, 'Could not update staff role.')
  }
}

async function handleLogout() {
  await auth.logout()
  if (typeof window !== 'undefined') {
    window.location.href = '/login'
  } else {
    await router.replace({ name: 'login' })
  }
}

function refreshAll() {
  refreshReadiness()
  loadProfile()
  loadAiSettings()
  loadWebmailSettings()
  loadSiteTheme()
  loadApiIntegrations()
  loadStaffUsers()
}

onMounted(() => {
  const initialTab = route.query.tab
  if (typeof initialTab === 'string' && initialTab.trim()) {
    settingsTab.value = initialTab.trim()
  }
  refreshAll()
})

watch(
  () => route.query.tab,
  (tab) => {
    if (typeof tab === 'string' && tab.trim() && tab !== settingsTab.value) {
      settingsTab.value = tab.trim()
    }
  },
)

watch(settingsTab, (tab) => {
  if (route.query.tab !== tab) {
    void router.replace({ query: { ...route.query, tab } })
  }
})
</script>

<template>
  <DashboardLayout @refresh="refreshAll">
    <div class="animate-fade-in space-y-5">
      <UiPageHeader title="Settings" lede="Account, theme, integrations, and staff administration" />

      <UiTabBar v-model="settingsTab" :items="settingsTabs" variant="flat" aria-label="Settings sections" />

      <div v-show="settingsTab === 'account'" class="space-y-5">
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
      </div>

      <div v-show="settingsTab === 'theme'" class="space-y-5">
      <Card title="Website & panel theme" subtitle="Brand colors for public site, customer portal, and staff dashboards">
        <div v-if="!canManageIntegrations" class="text-sm text-surface-muted">
          You need platform write permission to change the website theme.
        </div>
        <div v-else-if="siteThemeLoading" class="space-y-3">
          <Skeleton height="3rem" />
        </div>
        <div v-else class="space-y-5">
          <div class="grid gap-3 sm:grid-cols-2">
            <button
              v-for="opt in siteThemes.length
                ? siteThemes
                : [
                    {
                      id: 'studio-light',
                      name: 'Ember Studio',
                      description: 'Warm linen + IFNOTUS orange.',
                    },
                    {
                      id: 'ocean-clean',
                      name: 'Atlantic Mist',
                      description: 'Cool mist with deep cyan.',
                    },
                    {
                      id: 'graphite',
                      name: 'Baobab Indigo',
                      description: 'Chalk panels with indigo signal.',
                    },
                    {
                      id: 'palm-grove',
                      name: 'Palm Grove',
                      description: 'Celadon paper with deep green.',
                    },
                  ]"
              :key="opt.id"
              type="button"
              class="rounded-lg border p-3 text-left transition"
              :class="
                siteTheme === opt.id
                  ? 'border-brand-500 bg-brand-500/5'
                  : 'border-surface-border hover:border-brand-500/40'
              "
              @click="applyPresetColors(opt)"
            >
              <p class="text-sm font-semibold">{{ opt.name }}</p>
              <p class="mt-0.5 text-xs text-surface-muted">{{ opt.description }}</p>
              <div v-if="opt.colors" class="mt-2 flex gap-1">
                <span
                  v-for="(hex, key) in opt.colors"
                  :key="key"
                  class="h-3 w-3 rounded-full border border-black/10"
                  :style="{ background: hex }"
                  :title="String(key)"
                />
              </div>
            </button>
          </div>

          <div>
            <p class="mb-2 text-sm font-semibold">Brand colors</p>
            <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label v-for="key in Object.keys(siteColors)" :key="key" class="text-xs text-surface-muted">
                {{ key.replace('_', ' ') }}
                <div class="mt-1 flex items-center gap-2">
                  <input v-model="(siteColors as any)[key]" type="color" class="h-9 w-10 cursor-pointer rounded border border-surface-border bg-transparent p-0.5" />
                  <input v-model="(siteColors as any)[key]" type="text" class="w-full rounded border border-surface-border bg-surface-raised px-2 py-1.5 font-mono text-xs" />
                </div>
              </label>
            </div>
          </div>

          <div>
            <p class="mb-2 text-sm font-semibold">Homepage layout</p>
            <p class="mb-3 text-xs text-surface-muted">
              Three public homepage looks. Change anytime — no redeploy needed.
            </p>
            <div class="grid gap-3 sm:grid-cols-3">
              <button
                v-for="opt in (homeLayouts.length
                  ? homeLayouts
                  : [
                      { id: 'split-right', name: 'Split with image', description: 'Copy left, hero image right.' },
                      { id: 'centered', name: 'Centered domain check', description: 'Classic centered hero.' },
                      { id: 'bold-band', name: 'Bold accent band', description: 'Full-bleed brand band.' },
                    ])"
                :key="opt.id"
                type="button"
                class="rounded-lg border p-3 text-left transition"
                :class="
                  homeLayout === opt.id
                    ? 'border-brand-500 bg-brand-500/5'
                    : 'border-surface-border hover:border-brand-500/40'
                "
                @click="homeLayout = opt.id"
              >
                <p class="text-sm font-semibold">{{ opt.name }}</p>
                <p class="mt-0.5 text-xs text-surface-muted">{{ opt.description }}</p>
              </button>
            </div>
          </div>

          <div class="rounded-lg border border-surface-border p-4">
            <label class="flex items-start gap-3 text-sm">
              <input v-model="maintenanceMode" type="checkbox" class="mt-1" />
              <span>
                <span class="font-semibold">Maintenance page</span>
                <span class="mt-0.5 block text-xs text-surface-muted">
                  Public pages show a maintenance screen. Staff login at fpanel.ifnotus.space stays available.
                </span>
              </span>
            </label>
            <label class="mt-3 block text-xs text-surface-muted">
              Message
              <textarea
                v-model="maintenanceMessage"
                rows="2"
                class="mt-1 w-full rounded border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-slate-800"
                placeholder="IFNOTUS is under scheduled maintenance…"
              />
            </label>
          </div>

          <div>
            <p class="mb-2 text-sm font-semibold">Package accent colors</p>
            <p class="mb-3 text-xs text-surface-muted">
              Customers inherit an accent from their plan price tier (or a plan-specific accent).
            </p>
            <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label v-for="row in planColorEdits" :key="row.id" class="rounded-lg border border-surface-border p-3 text-xs">
                <span class="font-semibold text-slate-800 dark:text-slate-100">{{ row.label }}</span>
                <span class="mt-0.5 block text-surface-muted">≤ GHS {{ row.max_price }}</span>
                <div class="mt-2 flex items-center gap-2">
                  <input v-model="row.accent" type="color" class="h-9 w-10 cursor-pointer rounded border border-surface-border bg-transparent p-0.5" />
                  <input v-model="row.accent" type="text" class="w-full rounded border border-surface-border bg-surface-raised px-2 py-1.5 font-mono text-xs" />
                </div>
              </label>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-3">
            <button
              type="button"
              class="rounded-lg bg-brand-500 px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
              :disabled="siteThemeSaving"
              @click="saveSiteTheme"
            >
              {{ siteThemeSaving ? 'Saving…' : 'Save theme' }}
            </button>
            <p
              v-if="siteThemeMessage"
              class="text-sm"
              :class="siteThemeMessage.ok ? 'text-emerald-600' : 'text-red-600'"
            >
              {{ siteThemeMessage.text }}
            </p>
          </div>
        </div>
      </Card>

      </div>

      <div v-show="settingsTab === 'integrations'" class="space-y-5">
      <Card
        title="API integrations"
        subtitle="Namecheap, Paystack, SMTP, SMS — managed here, not by editing code"
      >
        <div v-if="!canManageIntegrations" class="text-sm text-surface-muted">
          You need platform write permission to manage API keys.
        </div>
        <div v-else-if="apiIntLoading" class="space-y-3">
          <Skeleton height="2.5rem" />
          <Skeleton height="6rem" />
        </div>
        <div v-else class="space-y-6">
          <div class="flex flex-wrap gap-2 text-xs">
            <Badge :variant="apiIntegrations?.namecheap.configured ? 'success' : 'warning'" dot size="sm">
              Namecheap {{ apiIntegrations?.namecheap.configured ? 'ready' : 'off' }}
            </Badge>
            <Badge :variant="apiIntegrations?.paystack.configured ? 'success' : 'warning'" dot size="sm">
              Paystack {{ apiIntegrations?.paystack.demo_mode ? 'demo' : 'live' }}
            </Badge>
            <Badge :variant="apiIntegrations?.smtp.configured ? 'success' : 'warning'" dot size="sm">
              SMTP {{ apiIntegrations?.smtp.configured ? 'ready' : 'off' }}
            </Badge>
            <Badge :variant="apiIntegrations?.sms.configured ? 'success' : 'warning'" dot size="sm">
              SMS {{ apiIntegrations?.sms.provider || 'none' }}
            </Badge>
          </div>

          <div class="grid gap-4 lg:grid-cols-2">
            <div class="space-y-3 rounded-lg border border-surface-border p-3">
              <div class="flex items-center justify-between">
                <p class="text-sm font-semibold">Namecheap</p>
                <span
                  v-if="apiIntegrations?.namecheap.configured"
                  class="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300"
                >
                  <i class="fa-solid fa-circle-check text-emerald-500" /> Ready
                </span>
              </div>
              <label class="block text-sm">
                <span class="text-surface-muted">API user</span>
                <input v-model="ncUser" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
              </label>
              <label class="block text-sm">
                <div class="flex items-center justify-between">
                  <span class="text-surface-muted">API key</span>
                  <span v-if="apiIntegrations?.namecheap.api_key_masked" class="text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                    <i class="fa-solid fa-circle-check" /> Key Saved: {{ apiIntegrations.namecheap.api_key_masked }}
                  </span>
                  <span v-else class="text-xs text-amber-600 dark:text-amber-400">Not set</span>
                </div>
                <input
                  v-model="ncKey"
                  type="password"
                  autocomplete="off"
                  class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm"
                  :placeholder="apiIntegrations?.namecheap.api_key_masked ? '••••••••  (Saved: ' + apiIntegrations.namecheap.api_key_masked + ' — leave blank to keep)' : 'Enter Namecheap API key'"
                />
              </label>
              <label class="block text-sm">
                <span class="text-surface-muted">Client IP (must be whitelisted at Namecheap)</span>
                <input v-model="ncIp" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm" />
              </label>
            </div>

            <div class="space-y-3 rounded-lg border border-surface-border p-3">
              <div class="flex items-center justify-between">
                <p class="text-sm font-semibold">Paystack</p>
                <span
                  v-if="apiIntegrations?.paystack.configured"
                  class="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300"
                >
                  <i class="fa-solid fa-circle-check text-emerald-500" /> Live
                </span>
                <span
                  v-else
                  class="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-950/60 dark:text-amber-300"
                >
                  Demo mode
                </span>
              </div>
              <label class="block text-sm">
                <span class="text-surface-muted">Public key</span>
                <input v-model="psPublic" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm" placeholder="pk_live_... or pk_test_..." />
              </label>
              <label class="block text-sm">
                <div class="flex items-center justify-between">
                  <span class="text-surface-muted">Secret key</span>
                  <span v-if="apiIntegrations?.paystack.secret_key_masked" class="text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                    <i class="fa-solid fa-circle-check" /> Secret Saved: {{ apiIntegrations.paystack.secret_key_masked }}
                  </span>
                  <span v-else class="text-xs text-amber-600 dark:text-amber-400">Not set</span>
                </div>
                <input
                  v-model="psSecret"
                  type="password"
                  autocomplete="off"
                  class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm"
                  :placeholder="apiIntegrations?.paystack.secret_key_masked ? '••••••••  (Saved: ' + apiIntegrations.paystack.secret_key_masked + ' — leave blank to keep)' : 'sk_live_... or sk_test_...'"
                />
              </label>
            </div>

            <div class="space-y-3 rounded-lg border border-surface-border p-3">
              <p class="text-sm font-semibold">Merchant Mobile Money</p>
              <p class="text-xs text-surface-muted">Shown on customer invoices as the merchant number (use your phone number for now). Customers pay this, then share the transaction ID. Confirm on Orders to activate hosting.</p>
              <label class="block text-sm">
                <span class="text-surface-muted">Network</span>
                <input v-model="momoNetwork" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
              </label>
              <label class="block text-sm">
                <span class="text-surface-muted">Merchant number</span>
                <input v-model="momoNumber" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm" />
              </label>
              <label class="block text-sm">
                <span class="text-surface-muted">Account name</span>
                <input v-model="momoAccount" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
              </label>
            </div>

            <div class="space-y-3 rounded-lg border border-surface-border p-3">
              <div class="flex items-center justify-between">
                <p class="text-sm font-semibold">SMTP email</p>
                <span
                  v-if="apiIntegrations?.smtp.configured"
                  class="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300"
                >
                  <i class="fa-solid fa-circle-check text-emerald-500" /> Ready
                </span>
              </div>
              <label class="block text-sm">
                <span class="text-surface-muted">Host</span>
                <input v-model="smtpHost" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" placeholder="smtp.example.com" />
              </label>
              <div class="grid grid-cols-2 gap-2">
                <label class="block text-sm">
                  <span class="text-surface-muted">Port</span>
                  <input v-model.number="smtpPort" type="number" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
                </label>
                <label class="flex items-end gap-2 pb-2 text-sm">
                  <input v-model="smtpTls" type="checkbox" />
                  <span>Use TLS</span>
                </label>
              </div>
              <label class="block text-sm">
                <span class="text-surface-muted">Username</span>
                <input v-model="smtpUser" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
              </label>
              <label class="block text-sm">
                <div class="flex items-center justify-between">
                  <span class="text-surface-muted">Password</span>
                  <span v-if="apiIntegrations?.smtp.password_masked || apiIntegrations?.smtp.password_set" class="text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                    <i class="fa-solid fa-circle-check" /> Password Saved
                  </span>
                  <span v-else class="text-xs text-amber-600 dark:text-amber-400">Not set</span>
                </div>
                <input
                  v-model="smtpPass"
                  type="password"
                  autocomplete="off"
                  class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm"
                  :placeholder="apiIntegrations?.smtp.password_set ? '••••••••  (Saved — leave blank to keep)' : 'Enter SMTP password'"
                />
              </label>
              <label class="block text-sm">
                <span class="text-surface-muted">From address</span>
                <input v-model="smtpFrom" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" placeholder="noreply@ifnotus.space" />
              </label>
            </div>

            <div class="space-y-3 rounded-lg border border-surface-border p-3">
              <div class="flex items-center justify-between">
                <p class="text-sm font-semibold">SMS Gateway</p>
                <span
                  v-if="apiIntegrations?.sms.configured"
                  class="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300"
                >
                  <i class="fa-solid fa-circle-check text-emerald-500" /> Active ({{ apiIntegrations.sms.provider }})
                </span>
                <span
                  v-else
                  class="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                >
                  <i class="fa-solid fa-circle-xmark text-slate-400" /> Not configured
                </span>
              </div>

              <label class="block text-sm">
                <span class="text-surface-muted">Provider</span>
                <select v-model="smsProvider" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm font-medium">
                  <option value="none">none</option>
                  <option value="log">log (dev)</option>
                  <option value="arkasel">Arkasel (Arkesel)</option>
                  <option value="moolre">Moolre</option>
                  <option value="hubtel">Hubtel</option>
                </select>
              </label>

              <label class="block text-sm">
                <div class="flex items-center justify-between">
                  <span class="text-surface-muted">API key</span>
                  <span v-if="apiIntegrations?.sms.api_key_masked" class="text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                    <i class="fa-solid fa-circle-check" /> Key Saved: {{ apiIntegrations.sms.api_key_masked }}
                  </span>
                  <span v-else class="text-xs text-amber-600 dark:text-amber-400">No key saved</span>
                </div>
                <div class="relative mt-1">
                  <input
                    v-model="smsKey"
                    type="password"
                    autocomplete="off"
                    class="w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm font-mono pr-10"
                    :placeholder="apiIntegrations?.sms.api_key_masked ? '••••••••  (Saved: ' + apiIntegrations.sms.api_key_masked + ' — leave blank to keep)' : 'Paste Arkasel / SMS API key here'"
                  />
                  <span v-if="apiIntegrations?.sms.api_key_masked && !smsKey" class="absolute right-3 top-2.5 text-xs text-emerald-600" title="API key is active and saved">
                    <i class="fa-solid fa-shield-halved" />
                  </span>
                </div>
              </label>

              <label v-if="smsProvider === 'hubtel'" class="block text-sm">
                <div class="flex items-center justify-between">
                  <span class="text-surface-muted">API secret (Hubtel only)</span>
                  <span v-if="apiIntegrations?.sms.api_secret_set" class="text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                    <i class="fa-solid fa-circle-check" /> Secret Saved
                  </span>
                </div>
                <input
                  v-model="smsSecret"
                  type="password"
                  autocomplete="off"
                  class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm font-mono"
                  :placeholder="apiIntegrations?.sms.api_secret_set ? '••••••••  (Saved — leave blank to keep)' : 'Hubtel client secret'"
                />
              </label>

              <label v-if="smsProvider === 'arkasel' || smsProvider === 'hubtel'" class="block text-sm">
                <div class="flex items-center justify-between">
                  <span class="text-surface-muted">Moolre fallback API key</span>
                  <span v-if="apiIntegrations?.sms.fallback_api_key_set" class="text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                    <i class="fa-solid fa-circle-check" /> Fallback Saved
                  </span>
                </div>
                <input
                  v-model="smsFallbackKey"
                  type="password"
                  autocomplete="off"
                  class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm font-mono"
                  :placeholder="apiIntegrations?.sms.fallback_api_key_set ? '••••••••  (Saved — leave blank to keep)' : 'Used automatically if Arkasel fails'"
                />
              </label>

              <label class="block text-sm">
                <span class="text-surface-muted">Sender ID</span>
                <input v-model="smsSender" class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm font-medium" placeholder="IFNOTUS" />
              </label>

              <!-- Live SMS Balance & Spend Tracking -->
              <div v-if="smsProvider !== 'none'" class="mt-3 space-y-2 rounded-lg bg-slate-50 p-3 dark:bg-slate-900/60 border border-surface-border">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-semibold uppercase tracking-wider text-surface-muted">SMS Balance &amp; Usage</span>
                  <button
                    type="button"
                    class="text-xs text-brand-600 hover:underline dark:text-brand-400 font-semibold disabled:opacity-50"
                    :disabled="smsBalanceLoading"
                    @click="loadSmsBalance"
                  >
                    {{ smsBalanceLoading ? 'Checking…' : '↻ Check Balance' }}
                  </button>
                </div>

                <div class="grid grid-cols-2 gap-2 text-xs">
                  <div class="rounded bg-white p-2.5 border border-surface-border dark:bg-slate-800">
                    <p class="text-surface-muted">Live Balance</p>
                    <p class="mt-0.5 text-sm font-bold text-slate-900 dark:text-white">
                      <span v-if="smsBalanceData?.sms_balance != null">{{ smsBalanceData.sms_balance }} SMS</span>
                      <span v-else-if="smsBalanceData?.main_balance != null">
                        {{ typeof smsBalanceData.main_balance === 'string' && smsBalanceData.main_balance.startsWith('GHS') ? smsBalanceData.main_balance : 'GHS ' + Number(smsBalanceData.main_balance).toFixed(2) }}
                      </span>
                      <span v-else-if="smsBalanceLoading" class="text-surface-muted text-xs">Loading…</span>
                      <span v-else class="text-surface-muted text-xs">Not checked</span>
                    </p>
                    <span v-if="smsBalanceData?.sms_balance != null && smsBalanceData?.main_balance != null" class="text-[10px] text-surface-muted block mt-0.5">
                      Credit: {{ smsBalanceData.main_balance }}
                    </span>
                  </div>
                  <div class="rounded bg-white p-2.5 border border-surface-border dark:bg-slate-800">
                    <p class="text-surface-muted">SMS Sent (Ledger)</p>
                    <p class="mt-0.5 text-sm font-bold text-slate-900 dark:text-white">
                      {{ smsBalanceData?.total_sms_sent ?? '—' }}
                      <span class="text-[10px] font-normal text-surface-muted block" v-if="smsBalanceData?.estimated_spent_ghs != null">
                        (~GHS {{ smsBalanceData.estimated_spent_ghs.toFixed(2) }} spent)
                      </span>
                    </p>
                  </div>
                </div>

                <p v-if="smsBalanceData?.message" class="text-[11px]" :class="smsBalanceData.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'">
                  <i class="fa-solid" :class="smsBalanceData.ok ? 'fa-check-circle mr-1' : 'fa-circle-exclamation mr-1'" />
                  {{ smsBalanceData.message }}
                </p>
              </div>
            </div>
          </div>

          <p
            v-if="apiIntMessage"
            class="text-sm"
            :class="apiIntMessage.ok ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-600'"
          >
            {{ apiIntMessage.text }}
          </p>

          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              :disabled="apiIntSaving"
              @click="saveApiIntegrations"
            >
              {{ apiIntSaving ? 'Saving…' : 'Save API keys' }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-surface-border px-4 py-2 text-sm disabled:opacity-50"
              :disabled="apiIntSaving"
              @click="importApiIntegrationsFromEnv"
            >
              Import from server .env
            </button>
            <button
              type="button"
              class="rounded-lg border border-surface-border px-4 py-2 text-sm"
              :disabled="apiIntSaving"
              @click="loadApiIntegrations"
            >
              Refresh
            </button>
          </div>
        </div>
      </Card>

      <Card
        title="Domain pricing & TLD fees (GHS)"
        subtitle="Manage selling prices for standalone and package domain registrations"
      >
        <div class="space-y-4">
          <p class="text-xs text-surface-muted">
            Set customer prices in GHS. When customers order a standalone domain or add a domain during checkout, these rates are applied.
          </p>

          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            <div
              v-for="(price, ext) in domainPrices"
              :key="ext"
              class="rounded-lg border border-surface-border p-3 space-y-1.5"
            >
              <div class="flex items-center justify-between">
                <span class="font-bold text-sm text-brand-600 dark:text-brand-400">{{ ext }}</span>
                <span class="text-[10px] uppercase font-semibold text-surface-muted">GHS/yr</span>
              </div>
              <input
                v-model.number="domainPrices[ext]"
                type="number"
                min="1"
                step="1"
                class="w-full rounded-md border border-surface-border bg-transparent px-2.5 py-1.5 text-sm font-semibold"
              />
            </div>
          </div>

          <div class="flex items-center justify-between pt-2">
            <p class="text-xs text-surface-muted">
              Standard: .online (65 GHS), .com (225 GHS). Changes take effect immediately.
            </p>
            <button
              type="button"
              class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              :disabled="apiIntSaving"
              @click="saveApiIntegrations"
            >
              {{ apiIntSaving ? 'Saving…' : 'Save Domain Prices' }}
            </button>
          </div>
        </div>
      </Card>

      </div>

      <div v-show="settingsTab === 'ai'" class="space-y-5">
      <Card title="AI agent" subtitle="Server companion for Files, Terminal & Editor">
        <div v-if="!canManageAi" class="text-sm text-surface-muted">
          Only superadmins can manage the AI agent API key.
        </div>
        <div v-else-if="aiLoading" class="space-y-3">
          <Skeleton height="2.5rem" />
          <Skeleton height="2.5rem" />
          <Skeleton height="2.5rem" width="40%" />
        </div>
        <div v-else class="space-y-4">
          <div class="flex flex-wrap items-center gap-2 text-sm">
            <Badge :variant="aiSettings?.configured ? 'success' : 'warning'" dot size="sm">
              {{ aiSettings?.configured ? 'Configured' : 'Not configured' }}
            </Badge>
            <span v-if="aiSettings?.api_key_masked" class="font-mono text-xs text-surface-muted">
              {{ aiSettings.api_key_masked }}
            </span>
          </div>

          <label class="block text-sm">
            <span class="text-surface-muted">Agent name</span>
            <input
              v-model="aiAgentName"
              class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm"
              placeholder="SNR Dev"
              maxlength="64"
            />
          </label>

          <label class="block text-sm">
            <span class="text-surface-muted">API key</span>
            <input
              v-model="aiKey"
              type="password"
              autocomplete="off"
              class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm"
              :placeholder="aiSettings?.configured ? '•••• leave blank to keep current key' : 'sk-…'"
            />
          </label>

          <label class="block text-sm">
            <span class="text-surface-muted">Model</span>
            <input
              v-model="aiModel"
              class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm"
              placeholder="chat model id"
            />
          </label>

          <p
            v-if="aiMessage"
            class="text-sm"
            :class="aiMessage.ok ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-600'"
          >
            {{ aiMessage.text }}
          </p>

          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              :disabled="aiSaving"
              @click="saveAiSettings"
            >
              {{ aiSaving ? 'Saving…' : 'Save' }}
            </button>
            <button
              v-if="aiSettings?.configured"
              type="button"
              class="rounded-lg border border-surface-border px-4 py-2 text-sm disabled:opacity-50"
              :disabled="aiSaving"
              @click="clearAiKey"
            >
              Clear key
            </button>
          </div>
        </div>
      </Card>

      </div>

      <div v-show="settingsTab === 'webmail'" class="space-y-5">
      <Card
        title="Webmail"
        subtitle="Support WhatsApp + auto-detect domains for /mail on every site"
      >
        <div v-if="!canManageWebmail" class="text-sm text-surface-muted">
          Only administrators can manage webmail settings.
        </div>
        <div v-else-if="webmailLoading" class="space-y-3">
          <Skeleton height="2.5rem" />
          <Skeleton height="2.5rem" />
        </div>
        <div v-else class="space-y-4">
          <p class="text-sm text-surface-muted">
            The Support link in Roundcube opens WhatsApp chat. New nginx domains get
            <span class="font-mono">/mail</span> automatically (same idea as app/database discovery).
          </p>

          <label class="block text-sm">
            <span class="text-surface-muted">Support WhatsApp number</span>
            <input
              v-model="webmailWhatsapp"
              type="tel"
              class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm"
              placeholder="+233541069241"
            />
          </label>

          <label class="block text-sm">
            <span class="text-surface-muted">Product name</span>
            <input
              v-model="webmailProduct"
              class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm"
              placeholder="IFNOTUS Webmail"
            />
          </label>

          <label class="flex items-center gap-2 text-sm">
            <input v-model="webmailAutoDetect" type="checkbox" class="rounded border-surface-border" />
            <span>Auto-detect new domains and expose <span class="font-mono">/mail</span></span>
          </label>

          <p
            v-if="webmailSettings?.support_url"
            class="text-xs text-surface-muted"
          >
            Preview:
            <a
              :href="webmailSettings.support_url"
              target="_blank"
              rel="noopener"
              class="font-mono text-brand-700 underline dark:text-brand-300"
            >{{ webmailSettings.support_url }}</a>
          </p>

          <p
            v-if="webmailMessage"
            class="text-sm"
            :class="webmailMessage.ok ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-600'"
          >
            {{ webmailMessage.text }}
          </p>

          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              :disabled="webmailSaving"
              @click="saveWebmailSettings"
            >
              {{ webmailSaving ? 'Saving…' : 'Save webmail' }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-surface-border px-4 py-2 text-sm disabled:opacity-50"
              :disabled="webmailSaving"
              @click="syncWebmailDomains"
            >
              Sync /mail now
            </button>
          </div>
        </div>
      </Card>

      </div>

      <div v-show="settingsTab === 'staff' && canManageStaff" class="space-y-5">
      <Card
        v-if="canManageStaff"
        title="Staff users"
        subtitle="Create staff for each unique privilege. Super admin alone manages these accounts. Client portal users stay under Customers."
      >
        <div class="grid gap-3 sm:grid-cols-2">
          <input v-model="staffName" placeholder="Full name" class="rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
          <input v-model="staffEmail" type="email" placeholder="Email" class="rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
          <input v-model="staffPassword" type="password" placeholder="Password (min 8)" class="rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm" />
          <select v-model="staffRole" class="rounded-lg border border-surface-border bg-transparent px-3 py-2 text-sm">
            <option value="admin">Business admin — plans, orders, customers, remediation</option>
            <option value="operator">Hosting operator — DNS, mail, files, databases, env ops</option>
            <option value="customer_care">Customer care — MoMo confirm &amp; support</option>
            <option value="viewer">Viewer — read only</option>
          </select>
        </div>
        <button type="button" class="mt-3 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white" @click="createStaffUser">
          Create &amp; activate staff
        </button>
        <p v-if="staffMsg" class="mt-2 text-sm text-surface-muted">{{ staffMsg }}</p>

        <div class="mt-5 overflow-x-auto rounded-lg border border-surface-border">
          <table class="min-w-full text-left text-sm">
            <thead class="bg-slate-50 text-xs uppercase tracking-wide text-surface-muted dark:bg-slate-900">
              <tr>
                <th class="px-3 py-2 font-semibold">Name</th>
                <th class="px-3 py-2 font-semibold">Role</th>
                <th class="px-3 py-2 font-semibold">Status</th>
                <th class="px-3 py-2 font-semibold" />
              </tr>
            </thead>
            <tbody>
              <tr v-if="staffLoading">
                <td colspan="4" class="px-3 py-3 text-surface-muted">Loading staff…</td>
              </tr>
              <tr v-else-if="!staffList.length">
                <td colspan="4" class="px-3 py-3 text-surface-muted">No staff users yet.</td>
              </tr>
              <tr
                v-for="row in staffList"
                :key="row.id"
                class="border-t border-surface-border"
              >
                <td class="px-3 py-2">
                  <div class="font-medium">{{ row.full_name || row.username }}</div>
                  <div class="text-xs text-surface-muted">{{ row.email }}</div>
                </td>
                <td class="px-3 py-2">
                  <select
                    v-if="!row.is_superuser && !(row.roles || []).includes('superadmin')"
                    class="rounded border border-surface-border bg-transparent px-2 py-1 text-xs"
                    :value="(row.roles || [])[0] || 'operator'"
                    @change="setStaffRole(row.id, ($event.target as HTMLSelectElement).value)"
                  >
                    <option value="admin">Business admin</option>
                    <option value="operator">Hosting operator</option>
                    <option value="customer_care">Customer care</option>
                    <option value="viewer">Viewer</option>
                  </select>
                  <span v-else class="text-xs font-semibold">Super admin</span>
                </td>
                <td class="px-3 py-2">
                  <Badge :variant="row.is_active ? 'success' : 'warning'" size="sm" dot>
                    {{ row.is_active ? 'Active' : 'Off' }}
                  </Badge>
                </td>
                <td class="px-3 py-2 text-right">
                  <button
                    v-if="!row.is_superuser && !(row.roles || []).includes('superadmin')"
                    type="button"
                    class="text-xs font-semibold text-blue-700 dark:text-blue-300"
                    @click="setStaffActive(row.id, !row.is_active)"
                  >
                    {{ row.is_active ? 'Deactivate' : 'Activate' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      </div>

      <div v-show="settingsTab === 'health'" class="space-y-5">
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

      <Card
        v-if="canManageSecurity"
        title="Access security"
        subtitle="Panel CIDR rules, login logs, and action audit"
      >
        <p class="mb-3 text-sm text-surface-muted">
          Manage IP allow/deny for the panel, login traces, action audit, and kill-switches.
        </p>
        <button
          type="button"
          class="rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700"
          @click="router.push({ name: 'security' })"
        >
          Open Security & Audit
        </button>
      </Card>

      </div>
    </div>
  </DashboardLayout>
</template>
