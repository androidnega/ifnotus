<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import UiTabBar from '@/components/ui/UiTabBar.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import { platformAdminApi } from '@/api'
import { getApiErrorMessage } from '@/lib/apiError'
import { IconEye, IconEyeOff } from '@/components/icons'
import { usePermissions } from '@/composables/usePermissions'
import { useAuthStore } from '@/stores/auth'
import { isPlatformOwner, getCanonicalRole } from '@/lib/roles'
import { Permission } from '@/lib/permissions'
import type {
  StaffAuditItem,
  StaffCustomerDetail,
  StaffCustomerListItem,
  StaffEnvHealth,
  StaffEnvLogs,
  StaffEnvStacks,
  StaffEnvUsage,
  StaffEnvironmentItem,
} from '@/types/staffPlatform'

const route = useRoute()
const auth = useAuthStore()
const { can } = usePermissions()

const canOps = computed(() => can(Permission.PLATFORM_OPS) || isPlatformOwner(auth.user))
const canProvision = computed(() => isPlatformOwner(auth.user) || can(Permission.SYSTEM_ADMIN) || can(Permission.PLATFORM_OPS))
const canTerminate = computed(() => isPlatformOwner(auth.user))
const canDelete = computed(() => isPlatformOwner(auth.user))
const canGrantCredits = computed(
  () => isPlatformOwner(auth.user) || can(Permission.BILLING_MANAGE),
)
const canEditProfile = computed(
  () => can(Permission.CUSTOMERS_MANAGE) || can(Permission.PLATFORM_OPS) || isPlatformOwner(auth.user),
)
const canEditSubdomain = computed(
  () => can(Permission.DOMAINS_WRITE) || can(Permission.PLATFORM_OPS) || isPlatformOwner(auth.user),
)

// Subdomain Modal State
const showEditSubdomainModal = ref(false)
const targetEnvForSubdomain = ref<StaffEnvironmentItem | null>(null)
const targetCustomerForSubdomain = ref<StaffCustomerListItem | null>(null)
const newSubdomainDomain = ref('')
const editSubdomainBusy = ref(false)
const editSubdomainError = ref('')

function openEditSubdomainModal(env: StaffEnvironmentItem, cust?: StaffCustomerListItem | null) {
  targetEnvForSubdomain.value = env
  targetCustomerForSubdomain.value = cust || null
  newSubdomainDomain.value = env.domain || ''
  editSubdomainError.value = ''
  showEditSubdomainModal.value = true
}

async function submitEditSubdomain() {
  const env = targetEnvForSubdomain.value || activeEnv.value
  if (!env || !newSubdomainDomain.value.trim()) {
    editSubdomainError.value = 'Please enter a valid subdomain or surname.'
    return
  }
  let raw = newSubdomainDomain.value.trim().toLowerCase()
  if (!raw.includes('.')) {
    raw = `${raw}.ifnotus.space`
  }
  editSubdomainBusy.value = true
  editSubdomainError.value = ''
  try {
    const { data } = await platformAdminApi.updateEnvironmentSubdomain(env.id, raw)
    msg.value = `Subdomain successfully assigned and live on ${data.domain || raw}!`
    showEditSubdomainModal.value = false
    await loadList()
    if (selected.value) {
      await openCustomer(selected.value.customer.id)
    }
  } catch (e: unknown) {
    editSubdomainError.value = getApiErrorMessage(e, 'Failed to update subdomain.')
  } finally {
    editSubdomainBusy.value = false
  }
}

// Credits & Profile State
const grantCredits = ref(50)
const grantNote = ref('')
const grantBusy = ref(false)
const editPhone = ref('')
const editEmail = ref('')
const editFirst = ref('')
const editLast = ref('')
const editCompany = ref('')
const profileBusy = ref(false)
const provisionPlanId = ref('')
const provisionDomain = ref('')
const allPlans = ref<import('@/types/platform').HostingPlan[]>([])
const deleteConfirmEmail = ref('')
const deleteBusy = ref(false)
const statusFilter = ref<'all' | 'live' | 'awaiting_payment' | 'setting_up' | 'none'>('all')

// Add Customer Modal
const showAddCustomerModal = ref(false)
const newCustFullName = ref('')
const newCustEmail = ref('')
const newCustPhone = ref('')
const newCustPassword = ref('')
const showNewCustPassword = ref(false)
const newCustCompany = ref('')
const newCustPlanId = ref('')
const newCustDomain = ref('')
const addCustBusy = ref(false)
const addCustError = ref('')

async function submitCreateCustomer() {
  if (!newCustEmail.value || !newCustFullName.value) {
    addCustError.value = 'Full name and email are required.'
    return
  }
  addCustBusy.value = true
  addCustError.value = ''
  try {
    const { data } = await platformAdminApi.createCustomer({
      email: newCustEmail.value.trim(),
      full_name: newCustFullName.value.trim(),
      phone: newCustPhone.value.trim() || undefined,
      password: newCustPassword.value.trim() || undefined,
      company: newCustCompany.value.trim() || undefined,
      plan_id: newCustPlanId.value || undefined,
      domain: newCustDomain.value.trim() || undefined,
    })
    showAddCustomerModal.value = false
    newCustFullName.value = ''
    newCustEmail.value = ''
    newCustPhone.value = ''
    newCustPassword.value = ''
    newCustCompany.value = ''
    newCustPlanId.value = ''
    newCustDomain.value = ''
    msg.value = `Customer ${data.email} created successfully!`
    await loadList()
    if (data.id) await openCustomer(data.id)
  } catch (e: unknown) {
    addCustError.value = getApiErrorMessage(e, 'Failed to create customer.')
  } finally {
    addCustBusy.value = false
  }
}

// Data List & Customer Detail Modal State
const customers = ref<StaffCustomerListItem[]>([])
const selected = ref<StaffCustomerDetail | null>(null)
const showDetailModal = ref(false)
const detailLoading = ref(false)
const detailTab = ref<'profile' | 'environments' | 'provision' | 'credits' | 'audit' | 'danger'>('profile')
const activeEnvId = ref<string | null>(null)
const q = ref('')
const loading = ref(true)
const error = ref('')
const msg = ref('')
const busy = ref(false)

// Pagination
const currentPage = ref(1)
const pageSize = ref(15)

const health = ref<StaffEnvHealth | null>(null)
const usage = ref<StaffEnvUsage | null>(null)
const stacks = ref<StaffEnvStacks | null>(null)
const logs = ref<StaffEnvLogs | null>(null)
const installStackId = ref('wordpress')
const envTab = ref<'overview' | 'health' | 'stacks' | 'logs' | 'activity'>('overview')

const envTabs = [
  { id: 'overview' as const, label: 'Overview' },
  { id: 'health' as const, label: 'Health' },
  { id: 'stacks' as const, label: 'Stacks' },
  { id: 'logs' as const, label: 'Logs' },
  { id: 'activity' as const, label: 'Activity' },
]

const activeEnv = computed(() =>
  selected.value?.environments.find((e) => e.id === activeEnvId.value) || null,
)

const isHostingOperator = computed(() => getCanonicalRole(auth.user) === 'hosting_operator')

const filteredCustomers = computed(() => {
  let list = customers.value
  if (isHostingOperator.value && statusFilter.value === 'all') {
    list = list.filter((c) => (c.hosting_status || 'none') !== 'awaiting_payment')
  } else if (statusFilter.value !== 'all') {
    list = list.filter((c) => (c.hosting_status || 'none') === statusFilter.value)
  }
  if (q.value.trim()) {
    const term = q.value.trim().toLowerCase()
    list = list.filter((c) =>
      c.full_name?.toLowerCase().includes(term) ||
      c.email?.toLowerCase().includes(term) ||
      c.phone?.toLowerCase().includes(term) ||
      c.primary_domain?.toLowerCase().includes(term) ||
      c.id?.toLowerCase().includes(term)
    )
  }
  return list
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredCustomers.value.length / pageSize.value)))

const paginatedCustomers = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredCustomers.value.slice(start, start + pageSize.value)
})

const showingStart = computed(() => (filteredCustomers.value.length === 0 ? 0 : (currentPage.value - 1) * pageSize.value + 1))
const showingEnd = computed(() => Math.min(currentPage.value * pageSize.value, filteredCustomers.value.length))

watch([statusFilter, q], () => {
  currentPage.value = 1
})

const statusCounts = computed(() => {
  const counts = { all: customers.value.length, live: 0, awaiting_payment: 0, setting_up: 0, none: 0 }
  for (const c of customers.value) {
    const s = c.hosting_status || 'none'
    if (s === 'live') counts.live += 1
    else if (s === 'awaiting_payment') counts.awaiting_payment += 1
    else if (s === 'setting_up') counts.setting_up += 1
    else if (s === 'none') counts.none += 1
  }
  return counts
})

// KPI Metrics
const totalCustomersCount = computed(() => customers.value.length)
const liveHostingCount = computed(() => statusCounts.value.live)
const awaitingPaymentCount = computed(() => statusCounts.value.awaiting_payment)
const totalEnvironmentsCount = computed(() =>
  customers.value.reduce((acc, c) => acc + (c.environment_count || 0), 0),
)
const totalAiCredits = computed(() =>
  customers.value.reduce((acc, c) => acc + (c.credits_remaining || 0), 0),
)

function hostingStatusLabel(status?: string | null) {
  switch (status) {
    case 'live':
      return 'Live'
    case 'awaiting_payment':
      return 'Payment to confirm'
    case 'setting_up':
      return 'Setting up'
    case 'suspended':
      return 'Suspended'
    case 'inactive':
      return 'Inactive'
    default:
      return 'No hosting'
  }
}

function stackLabel(env: StaffEnvironmentItem) {
  const s = env.stack as {
    stack?: string
    stack_name?: string
    name?: string
    installed_at?: string
  } | null
  if (!s) return 'No stack installed'
  const name = s.stack_name || s.name || s.stack || 'stack'
  const when = s.installed_at ? ` · ${new Date(String(s.installed_at)).toLocaleDateString()}` : ''
  return `${name}${when}`
}

function currentStackName() {
  const cur = stacks.value?.current as { stack?: string; name?: string } | null | undefined
  return cur?.stack || cur?.name || 'none'
}

function shortDomain(domain?: string | null, id?: string) {
  if (domain) return domain
  return id ? id.slice(0, 8) : '—'
}

function envHeadline(env: { hosting_name?: string | null; domain?: string | null; id: string }) {
  return env.hosting_name || shortDomain(env.domain, env.id)
}

function checkValue(val: unknown) {
  if (val == null) return '—'
  if (typeof val === 'boolean') return val ? 'yes' : 'no'
  return String(val)
}

function apiErr(e: unknown, fallback: string) {
  const err = e as { response?: { data?: { error?: { message?: string } } } }
  return err.response?.data?.error?.message ?? fallback
}

async function loadList() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await platformAdminApi.listCustomers({
      q: q.value.trim() || undefined,
    })
    customers.value = data
  } catch (e: unknown) {
    error.value = apiErr(e, 'Could not load customers.')
  } finally {
    loading.value = false
  }
}

async function openCustomer(id: string) {
  msg.value = ''
  deleteConfirmEmail.value = ''
  health.value = null
  usage.value = null
  stacks.value = null
  logs.value = null
  showDetailModal.value = true
  detailLoading.value = true
  try {
    const { data } = await platformAdminApi.getCustomer(id)
    selected.value = data
    syncEditForm()
    activeEnvId.value = data.environments[0]?.id ?? null
    if (activeEnvId.value) await loadEnvPanel(activeEnvId.value)
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not open customer.')
  } finally {
    detailLoading.value = false
  }
}

function closeCustomerModal() {
  showDetailModal.value = false
  selected.value = null
}

function syncEditForm() {
  if (!selected.value) return
  const c = selected.value.customer
  editPhone.value = c.phone || ''
  editEmail.value = c.email || ''
  editFirst.value = c.first_name || ''
  editLast.value = c.last_name || ''
  editCompany.value = c.company || ''
}

async function saveCustomerProfile() {
  if (!selected.value || !canEditProfile.value) return
  profileBusy.value = true
  msg.value = ''
  try {
    const { data } = await platformAdminApi.updateCustomer(selected.value.customer.id, {
      email: editEmail.value.trim() || undefined,
      phone: editPhone.value.trim() || undefined,
      first_name: editFirst.value.trim() || undefined,
      last_name: editLast.value.trim() || undefined,
      company: editCompany.value.trim() || undefined,
    })
    selected.value = {
      ...selected.value,
      customer: { ...selected.value.customer, ...data },
    }
    syncEditForm()
    msg.value = 'Contact details updated.'
    await loadList()
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not update contact details.')
  } finally {
    profileBusy.value = false
  }
}

async function deleteCustomer() {
  if (!selected.value || !canDelete.value) return
  const email = selected.value.customer.email
  const typed = deleteConfirmEmail.value.trim()
  if (typed.toLowerCase() !== email.toLowerCase()) {
    msg.value = `Type ${email} exactly to confirm deletion.`
    return
  }
  if (
    !confirm(
      `Permanently delete ${selected.value.customer.full_name}?\n\nThis terminates all environments and removes their login. Cannot be undone.`,
    )
  ) {
    return
  }
  deleteBusy.value = true
  try {
    const { data } = await platformAdminApi.deleteCustomer(selected.value.customer.id, typed)
    msg.value = data.message
    closeCustomerModal()
    deleteConfirmEmail.value = ''
    await loadList()
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not delete customer.')
  } finally {
    deleteBusy.value = false
  }
}

async function selectEnv(id: string) {
  activeEnvId.value = id
  envTab.value = 'overview'
  await loadEnvPanel(id)
}

async function loadEnvPanel(id: string) {
  if (!id) return
  try {
    const [u, s] = await Promise.all([
      platformAdminApi.getEnvironmentUsage(id),
      platformAdminApi.getEnvironmentStacks(id),
    ])
    usage.value = u.data
    stacks.value = s.data
    if (s.data.stacks?.length && !s.data.stacks.some((x) => x.id === installStackId.value)) {
      installStackId.value = s.data.stacks[0].id
    }
  } catch {
    /* keep prior */
  }
}

async function runHealth() {
  if (!activeEnvId.value || !canOps.value) return
  busy.value = true
  try {
    const { data } = await platformAdminApi.checkEnvironmentHealth(activeEnvId.value)
    health.value = data
    envTab.value = 'health'
    if (selected.value) await openCustomer(selected.value.customer.id)
    msg.value = data.summary || 'Health check completed.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Health check failed.')
  } finally {
    busy.value = false
  }
}

async function loadLogs() {
  if (!activeEnvId.value || !canOps.value) return
  busy.value = true
  try {
    const { data } = await platformAdminApi.getEnvironmentLogs(activeEnvId.value)
    logs.value = data
    envTab.value = 'logs'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not load logs.')
  } finally {
    busy.value = false
  }
}

async function suspendEnv(id: string) {
  if (!canOps.value || !confirm('Suspend this environment? Site goes offline; other tenants are untouched.')) return
  busy.value = true
  try {
    await platformAdminApi.suspendEnvironment(id)
    if (selected.value) await openCustomer(selected.value.customer.id)
    msg.value = 'Environment suspended.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Suspend failed.')
  } finally {
    busy.value = false
  }
}

async function restoreEnv(id: string) {
  if (!canOps.value) return
  busy.value = true
  try {
    await platformAdminApi.restoreEnvironment(id)
    if (selected.value) await openCustomer(selected.value.customer.id)
    msg.value = 'Environment restored.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Restore failed.')
  } finally {
    busy.value = false
  }
}

async function terminateEnv(id: string, domain?: string | null) {
  if (!canTerminate.value) return
  if (
    !confirm(
      `TERMINATE ${domain || id}?\n\nThis marks the site terminated and queues cleanup. Prefer Suspend for temporary issues.`,
    )
  ) {
    return
  }
  if (!confirm('Type confirmation: this cannot be undone from the customer portal. Continue?')) return
  busy.value = true
  try {
    await platformAdminApi.terminateEnvironment(id)
    if (selected.value) await openCustomer(selected.value.customer.id)
    msg.value = 'Environment terminated.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Terminate failed.')
  } finally {
    busy.value = false
  }
}

async function clearEnvStack(id: string, domain?: string | null) {
  if (!canOps.value) return
  const label = domain || id
  if (
    !confirm(
      `Clear the stack install for ${label}?\n\nDeletes site files in that environment only and leaves a parking page.`,
    )
  ) {
    return
  }
  const dropDb = confirm('Also drop this environment’s MySQL database? (Cancel = keep database)')
  busy.value = true
  try {
    const { data } = await platformAdminApi.clearEnvironmentStack(id, dropDb)
    if (selected.value) await openCustomer(selected.value.customer.id)
    msg.value = data.message || 'Installation cleared.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Clear failed.')
  } finally {
    busy.value = false
  }
}

async function repairFs(id: string) {
  if (!canOps.value) return
  busy.value = true
  try {
    const { data } = await platformAdminApi.repairEnvironmentFilesystem(id)
    msg.value = data.message || 'Permissions repaired.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Repair failed.')
  } finally {
    busy.value = false
  }
}

async function installStack() {
  if (!activeEnvId.value || !canOps.value || !installStackId.value) return
  if (!confirm(`Install ${installStackId.value} into this environment?`)) return
  busy.value = true
  try {
    const { data } = await platformAdminApi.installEnvironmentStack(
      activeEnvId.value,
      installStackId.value,
      false,
    )
    msg.value = (data as { message?: string }).message || 'Install queued.'
    await loadEnvPanel(activeEnvId.value)
    if (selected.value) await openCustomer(selected.value.customer.id)
    envTab.value = 'stacks'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Install failed.')
  } finally {
    busy.value = false
  }
}

async function grantCreditsToCustomer() {
  if (!selected.value || !canGrantCredits.value) return
  const amount = Math.floor(Number(grantCredits.value) || 0)
  if (amount < 1) {
    msg.value = 'Enter at least 1 credit.'
    return
  }
  if (!confirm(`Add ${amount} AI credit(s) to ${selected.value.customer.full_name || selected.value.customer.email}?`)) {
    return
  }
  grantBusy.value = true
  try {
    const { data } = await platformAdminApi.grantCustomerCredits(selected.value.customer.id, {
      credits: amount,
      note: grantNote.value.trim() || undefined,
    })
    selected.value.credits_remaining = data.credits_remaining
    const row = customers.value.find((c) => c.id === selected.value?.customer.id)
    if (row) row.credits_remaining = data.credits_remaining
    grantNote.value = ''
    msg.value = data.message
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not grant credits.')
  } finally {
    grantBusy.value = false
  }
}

async function provisionHosting() {
  if (!selected.value || !provisionPlanId.value) return
  const alreadyLive = (selected.value.environments || []).some(
    (e) => e.status === 'active' || e.health_status === 'healthy',
  )
  const warn = alreadyLive
    ? 'This customer already has live hosting. Activate anyway and create another environment?'
    : 'Set up hosting for this customer now? They will get SMS and email when it is live.'
  if (!confirm(warn)) return
  busy.value = true
  try {
    let domain = provisionDomain.value.trim().toLowerCase()
    if (domain && !domain.includes('.')) {
      domain = `${domain}.ifnotus.space`
    }
    let name: string | undefined
    let ext: string | undefined
    if (domain && domain.includes('.')) {
      const i = domain.indexOf('.')
      name = domain
      ext = domain.slice(i)
    }
    const { data } = await platformAdminApi.provisionCustomerHosting(selected.value.customer.id, {
      plan_id: provisionPlanId.value,
      domain_name: name,
      domain_extension: ext,
    })
    await openCustomer(selected.value.customer.id)
    const status = (data?.provisioning_status || '').toLowerCase()
    const newest = selected.value?.environments?.[0]
    const host = newest?.domain
    if (status === 'active') {
      msg.value = host
        ? `Hosting is live: ${host}. Customer notified (SMS/email if delivery succeeds).`
        : 'Hosting is live. Customer notified (SMS/email if delivery succeeds).'
    } else if (status === 'failed') {
      msg.value = 'Hosting setup failed. Check Activity / retry from Orders.'
    } else {
      msg.value = 'Hosting setup queued — refresh in a moment if the new environment is not listed yet.'
    }
    provisionDomain.value = ''
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not set up hosting.')
  } finally {
    busy.value = false
  }
}

const auditRows = computed<StaffAuditItem[]>(() => selected.value?.audit || [])

const envAuditRows = computed(() =>
  auditRows.value.filter(
    (r) => !r.target_id || r.target_id === activeEnv.value?.id || r.target_type !== 'environment',
  ),
)

function quickAssignSubdomainForCustomer(cust: StaffCustomerListItem) {
  openCustomer(cust.id).then(() => {
    if (selected.value?.environments?.length) {
      openEditSubdomainModal(selected.value.environments[0], cust)
    } else {
      detailTab.value = 'provision'
    }
  })
}

onMounted(async () => {
  await loadList()
  try {
    const { data } = await platformAdminApi.listPlans(false)
    allPlans.value = data
    if (data[0]) provisionPlanId.value = data[0].id
  } catch {
    allPlans.value = []
  }
  const open = route.query.open
  if (typeof open === 'string' && open) await openCustomer(open)
})

watch(
  () => route.query.open,
  async (open) => {
    if (typeof open === 'string' && open) await openCustomer(open)
  },
)
</script>

<template>
  <DashboardLayout flush>
    <div class="cust">
      <!-- HEADER -->
      <header class="cust-head-bar">
        <UiPageHeader
          title="Customers &amp; Tenants"
          lede="Manage tenant accounts, live infrastructure, student subdomains, and AI allocations."
        >
          <template #actions>
            <div class="head-btn-group">
              <button type="button" class="action-btn primary" @click="loadList">
                <i class="fa-solid fa-arrows-rotate" :class="{ 'fa-spin': loading }" aria-hidden="true" />
                Refresh
              </button>
              <button type="button" class="action-btn" @click="showAddCustomerModal = true">
                <i class="fa-solid fa-user-plus text-indigo-600 dark:text-indigo-400" aria-hidden="true" />
                + Add Customer
              </button>
            </div>
          </template>
        </UiPageHeader>
      </header>

      <div class="cust-body">
        <!-- TOP KPI STATS BAR -->
        <div class="stats-grid">
          <!-- 1. TOTAL ACCOUNTS -->
          <article class="stat-card tone-total">
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-users" /></span>
            <div class="stat-body">
              <span class="stat-k">Total Customers</span>
              <span class="stat-v">{{ totalCustomersCount }}</span>
              <span class="stat-s">Active accounts registered</span>
            </div>
          </article>

          <!-- 2. LIVE HOSTING -->
          <button
            type="button"
            class="stat-card tone-live"
            :class="{ active: statusFilter === 'live' }"
            @click="statusFilter = statusFilter === 'live' ? 'all' : 'live'"
          >
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-server" /></span>
            <div class="stat-body">
              <span class="stat-k">Live Hosting</span>
              <span class="stat-v">{{ liveHostingCount }}</span>
              <span class="stat-s">Production environments active</span>
            </div>
          </button>

          <!-- 3. AWAITING PAYMENT -->
          <button
            type="button"
            class="stat-card tone-await"
            :class="{ active: statusFilter === 'awaiting_payment' }"
            @click="statusFilter = statusFilter === 'awaiting_payment' ? 'all' : 'awaiting_payment'"
          >
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-clock-rotate-left" /></span>
            <div class="stat-body">
              <div class="stat-k-row">
                <span class="stat-k">Awaiting Confirm</span>
                <span v-if="awaitingPaymentCount > 0" class="badge-pulse">{{ awaitingPaymentCount }} pending</span>
              </div>
              <span class="stat-v">{{ awaitingPaymentCount }}</span>
              <span class="stat-s">Orders awaiting MoMo / review</span>
            </div>
          </button>

          <!-- 4. TOTAL ENVIRONMENTS -->
          <article class="stat-card tone-env">
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-cubes-stacked" /></span>
            <div class="stat-body">
              <span class="stat-k">Total Environments</span>
              <span class="stat-v">{{ totalEnvironmentsCount }}</span>
              <span class="stat-s">Linux jails &amp; PHP vhosts</span>
            </div>
          </article>

          <!-- 5. AI CREDITS POOL -->
          <article class="stat-card tone-ai">
            <span class="stat-icon" aria-hidden="true"><i class="fa-solid fa-brain" /></span>
            <div class="stat-body">
              <span class="stat-k">AI Credits Pool</span>
              <span class="stat-v">{{ totalAiCredits }}</span>
              <span class="stat-s">Total allocated balance</span>
            </div>
          </article>
        </div>

        <!-- FILTER & SEARCH CONTROLS CARD -->
        <section class="panel-card filters-card">
          <div class="filters-row">
            <!-- STATUS CHIP TABS -->
            <div class="filter-tabs">
              <button
                v-for="f in [
                  { id: 'all' as const, label: `All (${statusCounts.all})`, icon: 'fa-layer-group' },
                  { id: 'live' as const, label: `Live (${statusCounts.live})`, icon: 'fa-circle-check' },
                  { id: 'awaiting_payment' as const, label: `Awaiting Pay (${statusCounts.awaiting_payment})`, icon: 'fa-hourglass-half' },
                  { id: 'setting_up' as const, label: `Setting Up (${statusCounts.setting_up})`, icon: 'fa-gears' },
                  { id: 'none' as const, label: `No Hosting (${statusCounts.none})`, icon: 'fa-user' },
                ]"
                :key="f.id"
                type="button"
                class="filter-tab"
                :class="{ active: statusFilter === f.id }"
                @click="statusFilter = f.id"
              >
                <i class="fa-solid" :class="f.icon" aria-hidden="true" />
                <span>{{ f.label }}</span>
              </button>
            </div>

            <!-- SEARCH INPUT -->
            <div class="search-box">
              <i class="fa-solid fa-magnifying-glass search-icon" aria-hidden="true" />
              <input
                v-model="q"
                type="search"
                class="search-input"
                placeholder="Search customer, email, phone, domain, ID…"
                @keyup.enter="loadList"
              />
              <button v-if="q" type="button" class="btn-clear-search" title="Clear Search" @click="q = ''; loadList()">
                <i class="fa-solid fa-xmark" />
              </button>
            </div>
          </div>
        </section>

        <!-- GLOBAL STATUS ALERTS -->
        <UiAlert v-if="error" tone="err">{{ error }}</UiAlert>
        <UiAlert v-if="msg" :tone="msg.toLowerCase().includes('could not') || msg.toLowerCase().includes('fail') ? 'err' : 'ok'">
          {{ msg }}
        </UiAlert>

        <!-- CUSTOMERS LIST DATA TABLE -->
        <section class="panel-card table-card">
          <div class="card-head-compact">
            <div class="head-title-wrap">
              <h3 class="panel-title">
                <i class="fa-solid fa-users-gear text-indigo-600" />
                Customer Accounts &amp; Hosted Sites
              </h3>
              <span class="count-badge">{{ filteredCustomers.length }} in view</span>
            </div>

            <div v-if="filteredCustomers.length" class="pagination-sub-info">
              Showing {{ showingStart }}–{{ showingEnd }} of {{ filteredCustomers.length }}
            </div>
          </div>

          <div v-if="loading" class="state-msg">
            <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" />
            <span>Loading customer accounts &amp; live environments…</span>
          </div>

          <div v-else-if="filteredCustomers.length" class="cust-table-wrap">
            <table class="cust-table">
              <thead>
                <tr>
                  <th class="col-cust">Customer &amp; Account</th>
                  <th class="col-hosting">Hosting &amp; Subdomain</th>
                  <th class="col-status">Status &amp; Verification</th>
                  <th class="col-ai">AI Credits</th>
                  <th class="col-actions text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="c in paginatedCustomers"
                  :key="c.id"
                  class="cust-row cursor-pointer"
                  :class="{ 'row-live': c.hosting_status === 'live', 'row-awaiting': c.hosting_status === 'awaiting_payment' }"
                  @click="openCustomer(c.id)"
                >
                  <!-- 1. CUSTOMER & ACCOUNT -->
                  <td class="cell-cust">
                    <div class="row-top-info">
                      <span class="cust-name font-bold">{{ c.full_name || 'Customer' }}</span>
                      <span v-if="c.company" class="company-badge">{{ c.company }}</span>
                    </div>
                    <div class="cust-sub-details" @click.stop>
                      <a :href="`mailto:${c.email}`" class="cust-email-link" :title="c.email">
                        <i class="fa-solid fa-envelope text-slate-400" /> {{ c.email }}
                      </a>
                      <span v-if="c.phone" class="cust-phone-inline">
                        <span class="dot-sep">·</span>
                        <i class="fa-solid fa-phone text-slate-400" /> {{ c.phone }}
                      </span>
                    </div>
                  </td>

                  <!-- 2. HOSTING & SUBDOMAIN -->
                  <td class="cell-hosting">
                    <div class="row-top-info">
                      <div class="domain-tag-inline" :title="c.primary_domain || 'No domain assigned'">
                        <i class="fa-solid fa-globe text-indigo-500" />
                        <span class="domain-text font-semibold">
                          {{ c.primary_domain || 'No subdomain assigned' }}
                        </span>
                      </div>
                    </div>
                    <div class="env-count-sub">
                      <span>{{ c.environment_count }} environment{{ c.environment_count === 1 ? '' : 's' }}</span>
                      <span class="dot-sep">·</span>
                      <span>{{ c.subscription_count }} subscription{{ c.subscription_count === 1 ? '' : 's' }}</span>
                    </div>
                  </td>

                  <!-- 3. STATUS & VERIFICATION -->
                  <td class="cell-status">
                    <div class="row-top-info">
                      <span class="status-pill" :data-s="c.hosting_status || 'none'">
                        <i
                          class="fa-solid"
                          :class="{
                            'fa-circle-check text-emerald-500': c.hosting_status === 'live',
                            'fa-clock text-amber-500': c.hosting_status === 'awaiting_payment',
                            'fa-gears text-blue-500': c.hosting_status === 'setting_up',
                            'fa-user text-slate-400': !c.hosting_status || c.hosting_status === 'none',
                          }"
                        />
                        {{ hostingStatusLabel(c.hosting_status) }}
                      </span>
                    </div>
                    <div class="verif-sub">
                      <span class="badge-micro" :class="c.email_verified ? 'verified' : 'unverified'">
                        {{ c.email_verified ? 'Email Verified' : 'Unverified' }}
                      </span>
                      <span v-if="c.awaiting_payment_count" class="badge-micro awaiting-tag">
                        {{ c.awaiting_payment_count }} pending order
                      </span>
                    </div>
                  </td>

                  <!-- 4. AI CREDITS -->
                  <td class="cell-ai">
                    <div class="ai-credits-box">
                      <i class="fa-solid fa-bolt text-amber-500" />
                      <span class="ai-val">{{ c.credits_remaining }}</span>
                    </div>
                  </td>

                  <!-- 5. ACTIONS -->
                  <td class="cell-actions text-right" @click.stop>
                    <div class="actions-group">
                      <button
                        type="button"
                        class="btn-tbl-primary"
                        title="View Full Profile & Environments"
                        @click="openCustomer(c.id)"
                      >
                        <i class="fa-solid fa-eye" />
                        <span>Details</span>
                      </button>

                      <button
                        v-if="canEditSubdomain"
                        type="button"
                        class="btn-tbl-subdomain"
                        :title="c.primary_domain ? 'Update assigned subdomain' : 'Assign student surname subdomain'"
                        @click="quickAssignSubdomainForCustomer(c)"
                      >
                        <i class="fa-solid fa-pen-to-square" />
                        <span>{{ c.primary_domain ? 'Subdomain' : 'Assign Sub' }}</span>
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-else class="empty-box">
            <i class="fa-solid fa-user-slash text-slate-300 dark:text-slate-600 text-3xl" />
            <p class="empty-title">No customers found</p>
            <p class="empty-desc">No accounts match the selected filter or query. Try searching for a different name, email, or clear the search.</p>
          </div>

          <!-- PAGINATION FOOTER -->
          <footer v-if="filteredCustomers.length > pageSize" class="pagination-footer">
            <span class="pagination-summary">
              Showing <strong>{{ showingStart }}–{{ showingEnd }}</strong> of <strong>{{ filteredCustomers.length }}</strong>
            </span>
            <div class="pagination-controls">
              <button
                type="button"
                class="btn-page"
                :disabled="currentPage === 1"
                @click="currentPage = Math.max(1, currentPage - 1)"
              >
                <i class="fa-solid fa-chevron-left" /> Prev
              </button>
              <span class="page-indicator">Page {{ currentPage }} of {{ totalPages }}</span>
              <button
                type="button"
                class="btn-page"
                :disabled="currentPage === totalPages"
                @click="currentPage = Math.min(totalPages, currentPage + 1)"
              >
                Next <i class="fa-solid fa-chevron-right" />
              </button>
            </div>
          </footer>
        </section>
      </div>

      <!-- ADD CUSTOMER MODAL -->
      <div v-if="showAddCustomerModal" class="modal-backdrop" @click.self="showAddCustomerModal = false">
        <div class="modal-card">
          <div class="modal-head">
            <div class="modal-title-group">
              <i class="fa-solid fa-user-plus text-indigo-600" />
              <h3>Add New Customer Account</h3>
            </div>
            <button type="button" class="btn-close" @click="showAddCustomerModal = false">✕</button>
          </div>
          <p class="modal-sub">Create a customer account directly and optionally provision an initial hosting package.</p>

          <UiAlert v-if="addCustError" tone="err">{{ addCustError }}</UiAlert>

          <form class="modal-form" @submit.prevent="submitCreateCustomer">
            <div class="form-group">
              <label>Full Name *</label>
              <input v-model="newCustFullName" required placeholder="e.g. John Mensah" />
            </div>

            <div class="form-group">
              <label>Email Address *</label>
              <input v-model="newCustEmail" type="email" required placeholder="john@example.com" />
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>Phone Number (optional)</label>
                <input v-model="newCustPhone" placeholder="+233..." />
              </div>
              <div class="form-group">
                <label>Company / Institution (optional)</label>
                <input v-model="newCustCompany" placeholder="TTU / Organization" />
              </div>
            </div>

            <div class="form-group">
              <label>Password (optional, default auto-set)</label>
              <div class="input-eye-wrap">
                <input
                  v-model="newCustPassword"
                  :type="showNewCustPassword ? 'text' : 'password'"
                  placeholder="Leave blank for auto-generated password"
                />
                <button
                  type="button"
                  class="eye-btn"
                  :title="showNewCustPassword ? 'Hide password' : 'Show password'"
                  tabindex="-1"
                  @click="showNewCustPassword = !showNewCustPassword"
                >
                  <IconEyeOff v-if="showNewCustPassword" :size="18" />
                  <IconEye v-else :size="18" />
                </button>
              </div>
            </div>

            <div class="form-section-title">Initial Hosting Plan &amp; Subdomain (Optional)</div>
            <div class="form-row">
              <div class="form-group">
                <label>Hosting Plan</label>
                <select v-model="newCustPlanId">
                  <option value="">-- No hosting now --</option>
                  <option v-for="p in allPlans" :key="p.id" :value="p.id">
                    {{ p.name }} (₵{{ p.price_monthly }}/mo)
                  </option>
                </select>
              </div>
              <div v-if="newCustPlanId" class="form-group">
                <label>Assigned Subdomain / Domain</label>
                <input v-model="newCustDomain" placeholder="e.g. mensah.ifnotus.space" />
              </div>
            </div>

            <div class="modal-actions">
              <button type="button" class="btn-ghost" @click="showAddCustomerModal = false">Cancel</button>
              <button type="submit" class="btn-submit-primary" :disabled="addCustBusy">
                {{ addCustBusy ? 'Creating Customer…' : 'Create Customer' }}
              </button>
            </div>
          </form>
        </div>
      </div>

      <!-- EDIT / ASSIGN SUBDOMAIN MODAL -->
      <div v-if="showEditSubdomainModal" class="modal-backdrop" @click.self="showEditSubdomainModal = false">
        <div class="modal-card">
          <div class="modal-head">
            <div class="modal-title-group">
              <i class="fa-solid fa-bolt text-indigo-600" />
              <h3>Assign &amp; Customize Subdomain</h3>
            </div>
            <button type="button" class="btn-close" @click="showEditSubdomainModal = false">✕</button>
          </div>
          <p class="modal-sub">
            Assign a student project subdomain (e.g. enter <code>surname</code> to automatically route to <code>surname.ifnotus.space</code>) or specify a custom apex domain.
          </p>

          <UiAlert v-if="editSubdomainError" tone="err">{{ editSubdomainError }}</UiAlert>

          <form class="modal-form" @submit.prevent="submitEditSubdomain">
            <div class="form-group">
              <label>Subdomain / Domain Name *</label>
              <div class="input-addon-wrap">
                <input
                  v-model="newSubdomainDomain"
                  required
                  placeholder="e.g. mensah, blay, or customdomain.online"
                  autofocus
                />
              </div>
              <p class="field-hint">
                Tip: Typing a single name like <strong>blay</strong> will automatically assign <strong>blay.ifnotus.space</strong>.
              </p>
            </div>

            <div class="modal-actions">
              <button type="button" class="btn-ghost" :disabled="editSubdomainBusy" @click="showEditSubdomainModal = false">Cancel</button>
              <button type="submit" class="btn-submit-primary" :disabled="editSubdomainBusy">
                <i class="fa-solid fa-cloud-arrow-up mr-1" />
                {{ editSubdomainBusy ? 'Assigning Subdomain…' : 'Save & Route Subdomain' }}
              </button>
            </div>
          </form>
        </div>
      </div>

      <!-- FULL CUSTOMER DETAILS MODAL -->
      <div v-if="showDetailModal" class="modal-backdrop" @click.self="closeCustomerModal">
        <div class="modal-card wide customer-detail-modal">
          <div class="modal-head">
            <div class="modal-title-group">
              <i class="fa-solid fa-user-gear text-indigo-600" />
              <div>
                <h3 v-if="selected">{{ selected.customer.full_name }}</h3>
                <h3 v-else>Customer Details</h3>
                <p v-if="selected" class="text-xs text-slate-500 font-mono">{{ selected.customer.email }} · ID: {{ selected.customer.id.slice(0, 8) }}</p>
              </div>
            </div>
            <button type="button" class="btn-close" @click="closeCustomerModal">✕</button>
          </div>

          <div v-if="detailLoading" class="state-msg py-8">
            <i class="fa-solid fa-spinner fa-spin text-2xl" />
            <span>Fetching complete customer telemetry, environments, and logs…</span>
          </div>

          <template v-else-if="selected">
            <!-- MODAL TAB NAVIGATION -->
            <div class="modal-nav-tabs">
              <button
                type="button"
                class="modal-tab-btn"
                :class="{ active: detailTab === 'profile' }"
                @click="detailTab = 'profile'"
              >
                <i class="fa-solid fa-id-card" /> Profile
              </button>
              <button
                type="button"
                class="modal-tab-btn"
                :class="{ active: detailTab === 'environments' }"
                @click="detailTab = 'environments'"
              >
                <i class="fa-solid fa-server" /> Environments ({{ selected.environments.length }})
              </button>
              <button
                v-if="canProvision"
                type="button"
                class="modal-tab-btn"
                :class="{ active: detailTab === 'provision' }"
                @click="detailTab = 'provision'"
              >
                <i class="fa-solid fa-plus-circle" /> Provision Hosting
              </button>
              <button
                v-if="canGrantCredits"
                type="button"
                class="modal-tab-btn"
                :class="{ active: detailTab === 'credits' }"
                @click="detailTab = 'credits'"
              >
                <i class="fa-solid fa-bolt text-amber-500" /> AI Credits ({{ selected.credits_remaining }})
              </button>
              <button
                type="button"
                class="modal-tab-btn"
                :class="{ active: detailTab === 'audit' }"
                @click="detailTab = 'audit'"
              >
                <i class="fa-solid fa-clock-rotate-left" /> Audit Trail
              </button>
              <button
                v-if="canDelete"
                type="button"
                class="modal-tab-btn danger"
                :class="{ active: detailTab === 'danger' }"
                @click="detailTab = 'danger'"
              >
                <i class="fa-solid fa-trash" /> Danger Zone
              </button>
            </div>

            <!-- MODAL TAB BODIES -->
            <div class="modal-tab-content">
              <!-- TAB 1: PROFILE & CONTACT DETAILS -->
              <div v-if="detailTab === 'profile'" class="tab-pane">
                <form class="modal-form" @submit.prevent="saveCustomerProfile">
                  <div class="form-row">
                    <div class="form-group">
                      <label>Email Address</label>
                      <input v-model="editEmail" :disabled="!canEditProfile" type="email" required />
                    </div>
                    <div class="form-group">
                      <label>Phone Number</label>
                      <input v-model="editPhone" :disabled="!canEditProfile" placeholder="+233..." />
                    </div>
                  </div>
                  <div class="form-row">
                    <div class="form-group">
                      <label>First Name</label>
                      <input v-model="editFirst" :disabled="!canEditProfile" />
                    </div>
                    <div class="form-group">
                      <label>Last Name</label>
                      <input v-model="editLast" :disabled="!canEditProfile" />
                    </div>
                  </div>
                  <div class="form-group">
                    <label>Company / Institution</label>
                    <input v-model="editCompany" :disabled="!canEditProfile" />
                  </div>

                  <div v-if="canEditProfile" class="modal-actions mt-3">
                    <button type="submit" class="btn-submit-primary" :disabled="profileBusy">
                      {{ profileBusy ? 'Saving…' : 'Save Contact Details' }}
                    </button>
                  </div>
                </form>

                <!-- SUBSCRIPTIONS SUMMARY -->
                <div class="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
                  <h4 class="text-xs font-bold uppercase text-slate-500 mb-2">Active Subscriptions &amp; Resource Plans</h4>
                  <div v-if="selected.subscriptions.length" class="space-y-2">
                    <div
                      v-for="s in selected.subscriptions"
                      :key="s.id"
                      class="flex flex-wrap items-center justify-between p-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 text-xs"
                    >
                      <div>
                        <span class="font-bold text-slate-800 dark:text-slate-200">{{ s.plan_name || 'Hosting Plan' }}</span>
                        <span class="text-slate-500 ml-2 font-mono">ID: {{ s.id.slice(0, 8) }}</span>
                        <div class="text-[11px] text-slate-500 mt-0.5">
                          CPU: {{ s.cpu_allocated }} cores · RAM: {{ s.ram_allocated }} GB · Storage: {{ s.storage_allocated }} GB
                        </div>
                      </div>
                      <div class="text-right">
                        <span class="status-pill" :data-s="s.status">{{ s.status }}</span>
                        <span v-if="s.expires_at" class="block text-[10px] text-slate-400 mt-1">
                          Expires: {{ new Date(s.expires_at).toLocaleDateString() }}
                        </span>
                      </div>
                    </div>
                  </div>
                  <p v-else class="text-xs text-slate-400">No active subscriptions found for this account.</p>
                </div>
              </div>

              <!-- TAB 2: ENVIRONMENTS & SUBDOMAINS -->
              <div v-else-if="detailTab === 'environments'" class="tab-pane">
                <div v-if="selected.environments.length" class="space-y-4">
                  <div
                    v-for="env in selected.environments"
                    :key="env.id"
                    class="env-card p-4 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/30"
                  >
                    <div class="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-200 dark:border-slate-700">
                      <div>
                        <div class="flex items-center gap-2">
                          <i class="fa-solid fa-server text-indigo-600" />
                          <strong class="text-sm font-bold text-slate-900 dark:text-slate-100">{{ envHeadline(env) }}</strong>
                          <span class="status-pill status-pill-xs" :data-s="env.status">{{ env.status }}</span>
                        </div>
                        <p class="text-xs text-slate-500 font-mono mt-0.5">
                          Domain: {{ env.domain || 'No domain assigned' }} · Webroot: {{ env.document_root || 'public_html' }}
                        </p>
                      </div>

                      <!-- ASSIGN SUBDOMAIN BUTTON -->
                      <div class="flex items-center gap-2">
                        <button
                          v-if="canEditSubdomain"
                          type="button"
                          class="btn-action-primary"
                          title="Assign or change student subdomain"
                          @click="openEditSubdomainModal(env)"
                        >
                          <i class="fa-solid fa-bolt text-amber-300" />
                          <span>Assign / Edit Subdomain</span>
                        </button>
                      </div>
                    </div>

                    <!-- ENVIRONMENT DETAILS GRID -->
                    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 my-3 text-xs">
                      <div class="metric-mini-box">
                        <span class="metric-mini-label">Health</span>
                        <span class="font-semibold text-slate-800 dark:text-slate-200">{{ env.health_status || 'healthy' }}</span>
                      </div>
                      <div class="metric-mini-box">
                        <span class="metric-mini-label">Limits</span>
                        <span class="font-semibold text-slate-800 dark:text-slate-200">{{ env.cpu_limit }}c · {{ env.ram_limit_gb }}GB</span>
                      </div>
                      <div class="metric-mini-box">
                        <span class="metric-mini-label">Storage</span>
                        <span class="font-semibold text-slate-800 dark:text-slate-200">{{ env.storage_limit_gb }} GB</span>
                      </div>
                      <div class="metric-mini-box">
                        <span class="metric-mini-label">Stack</span>
                        <span class="font-semibold text-slate-800 dark:text-slate-200">{{ stackLabel(env) }}</span>
                      </div>
                    </div>

                    <!-- OPS CONTROLS -->
                    <div v-if="canOps" class="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-100 dark:border-slate-800">
                      <button type="button" class="btn-micro" :disabled="busy" @click="runHealth">
                        <i class="fa-solid fa-heart-pulse text-emerald-500" /> Run Health
                      </button>
                      <button type="button" class="btn-micro" :disabled="busy" @click="repairFs(env.id)">
                        <i class="fa-solid fa-wrench text-blue-500" /> Fix Permissions
                      </button>
                      <button
                        v-if="env.status === 'active'"
                        type="button"
                        class="btn-micro"
                        :disabled="busy"
                        @click="suspendEnv(env.id)"
                      >
                        <i class="fa-solid fa-pause text-amber-500" /> Suspend
                      </button>
                      <button
                        v-else-if="env.status === 'suspended'"
                        type="button"
                        class="btn-micro"
                        :disabled="busy"
                        @click="restoreEnv(env.id)"
                      >
                        <i class="fa-solid fa-play text-emerald-500" /> Restore
                      </button>
                      <button type="button" class="btn-micro" :disabled="busy" @click="clearEnvStack(env.id, env.domain)">
                        <i class="fa-solid fa-eraser text-orange-500" /> Clear Stack
                      </button>
                      <button
                        v-if="canTerminate"
                        type="button"
                        class="btn-micro text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30"
                        :disabled="busy"
                        @click="terminateEnv(env.id, env.domain)"
                      >
                        <i class="fa-solid fa-ban" /> Terminate
                      </button>
                    </div>
                  </div>
                </div>

                <div v-else class="empty-box py-6">
                  <i class="fa-solid fa-cubes-stacked text-3xl text-slate-300 dark:text-slate-600" />
                  <p class="empty-title">No environments provisioned</p>
                  <p class="empty-desc">This customer does not have any active Linux environments yet.</p>
                  <button
                    v-if="canProvision"
                    type="button"
                    class="btn-submit-primary mt-3"
                    @click="detailTab = 'provision'"
                  >
                    + Provision Initial Hosting
                  </button>
                </div>
              </div>

              <!-- TAB 3: PROVISION HOSTING -->
              <div v-else-if="detailTab === 'provision'" class="tab-pane">
                <form class="modal-form" @submit.prevent="provisionHosting">
                  <div class="form-group">
                    <label>Select Hosting Package *</label>
                    <select v-model="provisionPlanId" required>
                      <option v-for="p in allPlans" :key="p.id" :value="p.id">
                        {{ p.name }} — ₵{{ p.price_monthly }}/mo ({{ p.cpu_cores }} CPU, {{ p.ram_gb }}GB RAM, {{ p.storage_gb }}GB Disk)
                      </option>
                    </select>
                  </div>

                  <div class="form-group">
                    <label>Assigned Student Subdomain or Domain (Optional)</label>
                    <input
                      v-model="provisionDomain"
                      placeholder="e.g. blay (expands to blay.ifnotus.space) or customdomain.online"
                    />
                    <p class="field-hint">Leave blank to automatically allocate based on customer account slug.</p>
                  </div>

                  <div class="modal-actions">
                    <button type="submit" class="btn-submit-primary" :disabled="busy">
                      <i class="fa-solid fa-bolt mr-1" />
                      {{ busy ? 'Setting up server environment…' : 'Set Up & Activate Hosting' }}
                    </button>
                  </div>
                </form>
              </div>

              <!-- TAB 4: AI CREDITS -->
              <div v-else-if="detailTab === 'credits'" class="tab-pane">
                <div class="flex items-center justify-between p-3 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 mb-4">
                  <div>
                    <span class="text-xs font-bold text-amber-900 dark:text-amber-200 block">Current AI Balance</span>
                    <strong class="text-2xl text-amber-700 dark:text-amber-400 font-extrabold">{{ selected.credits_remaining }} Credits</strong>
                  </div>
                  <i class="fa-solid fa-brain text-3xl text-amber-400" />
                </div>

                <form class="modal-form" @submit.prevent="grantCreditsToCustomer">
                  <div class="form-row">
                    <div class="form-group">
                      <label>Credits to Grant *</label>
                      <input v-model.number="grantCredits" type="number" min="1" max="100000" required />
                    </div>
                    <div class="form-group">
                      <label>Internal Note / Reason</label>
                      <input v-model="grantNote" placeholder="e.g. Student grant / complimentary bonus" />
                    </div>
                  </div>

                  <div class="modal-actions">
                    <button type="submit" class="btn-submit-primary" :disabled="grantBusy">
                      {{ grantBusy ? 'Granting…' : 'Grant AI Credits' }}
                    </button>
                  </div>
                </form>
              </div>

              <!-- TAB 5: AUDIT TRAIL -->
              <div v-else-if="detailTab === 'audit'" class="tab-pane">
                <div v-if="auditRows.length" class="space-y-2 max-h-72 overflow-y-auto pr-1">
                  <div
                    v-for="a in auditRows"
                    :key="a.id"
                    class="p-2.5 rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 text-xs"
                  >
                    <div class="flex items-center justify-between">
                      <strong class="text-slate-800 dark:text-slate-200 font-mono">{{ a.action }}</strong>
                      <span class="text-slate-400 text-[10px]">{{ new Date(a.occurred_at).toLocaleString() }}</span>
                    </div>
                    <div class="text-slate-600 dark:text-slate-400 mt-1 flex flex-wrap items-center gap-2 text-[11px]">
                      <span>Target: <code>{{ a.target_type }}#{{ a.target_id?.slice(0, 8) }}</code></span>
                      <span>Result: <span class="text-emerald-600 font-bold">{{ a.result }}</span></span>
                    </div>
                  </div>
                </div>
                <p v-else class="text-xs text-slate-400">No activity recorded yet for this customer account.</p>
              </div>

              <!-- TAB 6: DANGER ZONE -->
              <div v-else-if="detailTab === 'danger'" class="tab-pane">
                <div class="p-4 rounded-xl border border-rose-200 dark:border-rose-900 bg-rose-50/50 dark:bg-rose-950/20">
                  <h4 class="text-sm font-bold text-rose-700 dark:text-rose-400">Permanently Delete Customer Account</h4>
                  <p class="text-xs text-rose-600 dark:text-rose-300 mt-1">
                    This terminates all hosting environments, deletes user accounts, and wipes platform access. This action cannot be undone.
                  </p>

                  <div class="form-group mt-3">
                    <label class="text-xs font-bold text-rose-800 dark:text-rose-300">
                      Type <code>{{ selected.customer.email }}</code> to confirm:
                    </label>
                    <input v-model="deleteConfirmEmail" placeholder="Type email address exactly" />
                  </div>

                  <button
                    type="button"
                    class="btn-danger mt-2"
                    :disabled="deleteBusy || deleteConfirmEmail.trim().toLowerCase() !== selected.customer.email.toLowerCase()"
                    @click="deleteCustomer"
                  >
                    {{ deleteBusy ? 'Deleting Customer…' : 'Permanently Delete Account' }}
                  </button>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.cust {
  width: 100%;
  max-width: 100%;
  min-height: 100%;
  display: flex;
  flex-direction: column;
  overflow-x: hidden !important;
  box-sizing: border-box;
  background: #f8fafc;
}

/* HEADER & CONTROLS */
.cust-head-bar {
  padding: 0.85rem 1.25rem 0.5rem;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  overflow-x: hidden !important;
}

.head-btn-group {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.45rem;
  max-width: 100%;
  box-sizing: border-box;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  background: #ffffff;
  color: #334155;
  font-size: 0.76rem;
  font-weight: 650;
  padding: 0.38rem 0.65rem;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
  flex-shrink: 0;
}

.action-btn:hover {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}

.action-btn.primary {
  background: #1e3a5f;
  color: #ffffff;
  border-color: #1e3a5f;
}

.action-btn.primary:hover {
  background: #0f243e;
}

/* BODY */
.cust-body {
  flex: 1;
  width: 100%;
  max-width: 100%;
  padding: 1rem 1.25rem 2.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow-x: hidden !important;
  box-sizing: border-box;
}

/* KPI STATS GRID */
.stats-grid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #ffffff;
  padding: 0.85rem 1rem;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03);
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
  min-width: 0;
  box-sizing: border-box;
  overflow: hidden;
}

.stat-card:hover {
  border-color: #94a3b8;
  transform: translateY(-1px);
}

.stat-card.active {
  border-color: #1e3a5f;
  box-shadow: 0 0 0 2px rgba(30, 58, 95, 0.15);
}

.stat-icon {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 0.7rem;
  display: grid;
  place-items: center;
  font-size: 1.05rem;
  flex-shrink: 0;
}

.stat-body {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.stat-k-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem;
}

.stat-k {
  display: block;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-v {
  display: block;
  margin-top: 0.15rem;
  font-size: 1.25rem;
  font-weight: 850;
  color: #0f172a;
  line-height: 1.15;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-s {
  display: block;
  margin-top: 0.2rem;
  font-size: 0.72rem;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badge-pulse {
  font-size: 0.62rem;
  font-weight: 800;
  background: #f59e0b;
  color: #ffffff;
  padding: 0.1rem 0.4rem;
  border-radius: 999px;
  animation: pulse 2s infinite;
  flex-shrink: 0;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.tone-total .stat-icon { background: #e0f2fe; color: #0369a1; }
.tone-live .stat-icon { background: #d1fae5; color: #047857; }
.tone-await .stat-icon { background: #fef3c7; color: #b45309; }
.tone-env .stat-icon { background: #ede9fe; color: #6d28d9; }
.tone-ai .stat-icon { background: #fef9c3; color: #a16207; }

/* PANEL & FILTER CARDS */
.panel-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03);
  box-sizing: border-box;
  width: 100%;
  max-width: 100%;
}

.filters-card {
  padding: 0.75rem 1rem;
}

.filters-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.filter-tabs {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: 1px solid transparent;
  background: #f1f5f9;
  color: #475569;
  font-size: 0.74rem;
  font-weight: 650;
  padding: 0.3rem 0.6rem;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.12s ease;
}

.filter-tab:hover {
  color: #0f172a;
  background: #e2e8f0;
}

.filter-tab.active {
  background: #1e3a5f;
  color: #ffffff;
  font-weight: 750;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
  min-width: 240px;
  max-width: 320px;
  flex: 1;
}

.search-icon {
  position: absolute;
  left: 0.65rem;
  color: #94a3b8;
  font-size: 0.78rem;
  pointer-events: none;
}

.search-input {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  padding: 0.35rem 1.8rem 0.35rem 2rem;
  font-size: 0.76rem;
  color: #0f172a;
  background: #ffffff;
  outline: none;
  box-sizing: border-box;
}

.search-input:focus {
  border-color: #2563eb;
}

.btn-clear-search {
  position: absolute;
  right: 0.5rem;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  font-size: 0.75rem;
}

/* TABLE CARD */
.table-card {
  padding: 0.85rem 1rem;
}

.card-head-compact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 0.65rem;
  border-bottom: 1px solid #f1f5f9;
  margin-bottom: 0.5rem;
}

.head-title-wrap {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.panel-title {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 800;
  color: #0f172a;
}

.count-badge {
  font-size: 0.68rem;
  font-weight: 700;
  background: #f1f5f9;
  color: #475569;
  padding: 0.15rem 0.45rem;
  border-radius: 0.4rem;
}

.pagination-sub-info {
  font-size: 0.72rem;
  color: #64748b;
  font-weight: 600;
}

/* TABLE CONTAINER & ROWS */
.cust-table-wrap {
  overflow-x: hidden !important;
  overflow-y: auto !important;
  max-height: calc(100vh - 280px);
  min-height: 320px;
  width: 100% !important;
  max-width: 100% !important;
  position: relative;
  scrollbar-width: thin;
  scrollbar-color: #cbd5e1 transparent;
  box-sizing: border-box;
}

.cust-table-wrap::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}

.cust-table-wrap::-webkit-scrollbar-track {
  background: transparent;
}

.cust-table-wrap::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}

.cust-table {
  width: 100% !important;
  max-width: 100% !important;
  table-layout: fixed !important;
  border-collapse: collapse;
  font-size: 0.76rem;
  text-align: left;
  box-sizing: border-box;
}

.cust-table thead {
  position: sticky;
  top: 0;
  z-index: 10;
  background: #f8fafc;
}

.cust-table th {
  padding: 0.5rem 0.65rem;
  font-size: 0.65rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  border-bottom: 1.5px solid #e2e8f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  box-sizing: border-box;
}

.col-cust { width: 34%; }
.col-hosting { width: 28%; }
.col-status { width: 18%; }
.col-ai { width: 8%; text-align: center; }
.col-actions { width: 12%; text-align: right; }

.cust-table td {
  padding: 0.45rem 0.65rem;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 0;
  box-sizing: border-box;
}

.cust-row {
  transition: background 0.1s ease;
}

.cust-row:hover {
  background: #f1f5f9;
}

.cust-name {
  font-size: 0.8rem;
  color: #0f172a;
}

.company-badge {
  font-size: 0.65rem;
  background: #e0e7ff;
  color: #3730a3;
  padding: 0.05rem 0.35rem;
  border-radius: 0.3rem;
  font-weight: 600;
}

.cust-sub-details {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.7rem;
  color: #64748b;
  margin-top: 0.15rem;
}

.cust-email-link {
  color: #2563eb;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cust-email-link:hover {
  text-decoration: underline;
}

.dot-sep {
  color: #94a3b8;
}

.domain-tag-inline {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  color: #1e3a5f;
  font-size: 0.76rem;
}

.domain-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-count-sub {
  font-size: 0.68rem;
  color: #64748b;
  margin-top: 0.15rem;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.68rem;
  font-weight: 750;
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
}

.status-pill[data-s="live"], .status-pill[data-s="active"] {
  background: #dcfce7;
  color: #166534;
}

.status-pill[data-s="awaiting_payment"] {
  background: #fef3c7;
  color: #92400e;
}

.status-pill[data-s="setting_up"] {
  background: #e0e7ff;
  color: #3730a3;
}

.status-pill[data-s="suspended"] {
  background: #fee2e2;
  color: #991b1b;
}

.badge-micro {
  font-size: 0.62rem;
  padding: 0.05rem 0.3rem;
  border-radius: 0.25rem;
  font-weight: 600;
}

.badge-micro.verified {
  background: #dcfce7;
  color: #15803d;
}

.badge-micro.unverified {
  background: #f1f5f9;
  color: #64748b;
}

.badge-micro.awaiting-tag {
  background: #fef3c7;
  color: #b45309;
}

.verif-sub {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  margin-top: 0.15rem;
}

.ai-credits-box {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  padding: 0.15rem 0.45rem;
  border-radius: 0.45rem;
}

.ai-val {
  font-weight: 800;
  color: #b45309;
  font-size: 0.74rem;
}

.actions-group {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.25rem;
}

.btn-tbl-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  background: #1e3a5f;
  color: #ffffff;
  border: none;
  font-size: 0.7rem;
  font-weight: 750;
  padding: 0.25rem 0.5rem;
  border-radius: 0.4rem;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-tbl-primary:hover {
  background: #0f243e;
}

.btn-tbl-subdomain {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.25rem 0.45rem;
  border-radius: 0.4rem;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-tbl-subdomain:hover {
  background: #dbeafe;
}

/* PAGINATION FOOTER */
.pagination-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 0.75rem;
  border-top: 1px solid #f1f5f9;
  margin-top: 0.5rem;
}

.pagination-summary {
  font-size: 0.74rem;
  color: #64748b;
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.btn-page {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.25rem 0.55rem;
  border-radius: 0.4rem;
  cursor: pointer;
}

.btn-page:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-indicator {
  font-size: 0.74rem;
  color: #475569;
  font-weight: 700;
  padding: 0 0.35rem;
}

/* MODALS */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  z-index: 999;
  display: grid;
  place-items: center;
  padding: 1rem;
}

.modal-card {
  background: #ffffff;
  border-radius: 1rem;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  width: 100%;
  max-width: 540px;
  padding: 1.5rem;
  position: relative;
  border: 1px solid #e2e8f0;
  box-sizing: border-box;
}

.modal-card.wide {
  max-width: 820px;
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.5rem;
}

.modal-title-group {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.modal-title-group h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 800;
  color: #0f172a;
}

.btn-close {
  background: transparent;
  border: none;
  font-size: 1.1rem;
  color: #94a3b8;
  cursor: pointer;
  padding: 0.2rem;
}

.btn-close:hover {
  color: #0f172a;
}

.modal-sub {
  font-size: 0.78rem;
  color: #64748b;
  margin: 0 0 1rem;
  line-height: 1.35;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.form-group label {
  font-size: 0.72rem;
  font-weight: 750;
  color: #475569;
}

.form-group input,
.form-group select {
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  padding: 0.45rem 0.65rem;
  font-size: 0.78rem;
  color: #0f172a;
  background: #ffffff;
  outline: none;
}

.form-group input:focus,
.form-group select:focus {
  border-color: #2563eb;
}

.form-section-title {
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid #f1f5f9;
}

.field-hint {
  font-size: 0.7rem;
  color: #64748b;
  margin: 0.2rem 0 0;
}

.modal-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.btn-ghost {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #475569;
  font-size: 0.76rem;
  font-weight: 700;
  padding: 0.4rem 0.75rem;
  border-radius: 0.5rem;
  cursor: pointer;
}

.btn-submit-primary {
  border: none;
  background: #1e3a5f;
  color: #ffffff;
  font-size: 0.76rem;
  font-weight: 750;
  padding: 0.45rem 0.9rem;
  border-radius: 0.5rem;
  cursor: pointer;
}

.btn-submit-primary:hover {
  background: #0f243e;
}

.btn-action-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: #1e3a5f;
  color: #ffffff;
  border: none;
  font-size: 0.72rem;
  font-weight: 750;
  padding: 0.3rem 0.6rem;
  border-radius: 0.45rem;
  cursor: pointer;
}

.btn-action-primary:hover {
  background: #0f243e;
}

.btn-micro {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  font-size: 0.68rem;
  font-weight: 700;
  color: #334155;
  padding: 0.25rem 0.45rem;
  border-radius: 0.35rem;
  cursor: pointer;
}

.btn-micro:hover {
  background: #f1f5f9;
}

.btn-danger {
  border: none;
  background: #e11d48;
  color: #ffffff;
  font-size: 0.76rem;
  font-weight: 750;
  padding: 0.45rem 0.9rem;
  border-radius: 0.5rem;
  cursor: pointer;
}

.btn-danger:hover {
  background: #be123c;
}

.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.metric-mini-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  padding: 0.45rem 0.6rem;
  display: flex;
  flex-direction: column;
}

.metric-mini-label {
  font-size: 0.62rem;
  font-weight: 750;
  text-transform: uppercase;
  color: #64748b;
}

/* MODAL NAV TABS */
.modal-nav-tabs {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 0.5rem;
  margin-bottom: 1rem;
  overflow-x: auto;
}

.modal-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 700;
  padding: 0.35rem 0.6rem;
  border-radius: 0.45rem;
  cursor: pointer;
  white-space: nowrap;
}

.modal-tab-btn:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-tab-btn.active {
  background: #eff6ff;
  color: #2563eb;
}

.modal-tab-btn.danger.active {
  background: #fee2e2;
  color: #dc2626;
}

.input-eye-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.input-eye-wrap input {
  width: 100%;
  padding-right: 2.2rem;
}

.eye-btn {
  position: absolute;
  right: 0.5rem;
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
}

.state-msg {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 3rem 1rem;
  color: #64748b;
  font-size: 0.8rem;
  font-weight: 600;
}

.empty-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 1.5rem;
  text-align: center;
}

.empty-title {
  margin: 0.75rem 0 0.25rem;
  font-size: 0.88rem;
  font-weight: 800;
  color: #0f172a;
}

.empty-desc {
  margin: 0;
  font-size: 0.74rem;
  color: #64748b;
  max-width: 360px;
}
</style>
