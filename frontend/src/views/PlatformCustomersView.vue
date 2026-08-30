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
const canOps = computed(() => can(Permission.PLATFORM_OPS))
const canProvision = computed(() => isPlatformOwner(auth.user) || can(Permission.SYSTEM_ADMIN))
const canTerminate = computed(() => isPlatformOwner(auth.user))
const canDelete = computed(() => isPlatformOwner(auth.user))
const canGrantCredits = computed(
  () => isPlatformOwner(auth.user) || can(Permission.BILLING_MANAGE),
)
const canEditProfile = computed(
  () => can(Permission.CUSTOMERS_MANAGE) || can(Permission.PLATFORM_OPS) || isPlatformOwner(auth.user),
)
const canEditSubdomain = computed(
  () => can(Permission.DOMAINS_WRITE) || isPlatformOwner(auth.user),
)
const showEditSubdomainModal = ref(false)
const newSubdomainDomain = ref('')
const editSubdomainBusy = ref(false)
const editSubdomainError = ref('')

function openEditSubdomainModal(env: StaffEnvironmentItem) {
  newSubdomainDomain.value = env.domain || ''
  editSubdomainError.value = ''
  showEditSubdomainModal.value = true
}

async function submitEditSubdomain() {
  if (!activeEnv.value || !newSubdomainDomain.value.trim()) {
    editSubdomainError.value = 'Please enter a valid subdomain/domain.'
    return
  }
  editSubdomainBusy.value = true
  editSubdomainError.value = ''
  try {
    const { data } = await platformAdminApi.updateEnvironmentSubdomain(
      activeEnv.value.id,
      newSubdomainDomain.value.trim().toLowerCase(),
    )
    msg.value = `Subdomain updated to ${data.domain || newSubdomainDomain.value}!`
    showEditSubdomainModal.value = false
    if (selected.value) {
      await openCustomer(selected.value.customer.id)
    }
  } catch (e: unknown) {
    editSubdomainError.value = getApiErrorMessage(e, 'Failed to update subdomain.')
  } finally {
    editSubdomainBusy.value = false
  }
}

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

const customers = ref<StaffCustomerListItem[]>([])
const selected = ref<StaffCustomerDetail | null>(null)
const activeEnvId = ref<string | null>(null)
const q = ref('')
const loading = ref(true)
const error = ref('')
const msg = ref('')
const busy = ref(false)
const showList = ref(true)

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

const isAwaitingBilling = computed(() => {
  if (!selected.value) return false
  const status = selected.value.customer?.hosting_status || ''
  const hasUnclearedOrder = selected.value.orders?.some(
    (o) => o.payment_status === 'submitted' || o.payment_status === 'pending',
  )
  return status === 'awaiting_payment' || (Boolean(hasUnclearedOrder) && !selected.value.environments?.length)
})

const filteredCustomers = computed(() => {
  let list = customers.value
  if (isHostingOperator.value && statusFilter.value === 'all') {
    // For hosting operators, default view filters out uncleared accounts awaiting billing confirmation
    list = list.filter((c) => (c.hosting_status || 'none') !== 'awaiting_payment')
  } else if (statusFilter.value !== 'all') {
    list = list.filter((c) => (c.hosting_status || 'none') === statusFilter.value)
  }
  return list
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
  if (typeof val === 'object') {
    try {
      return JSON.stringify(val)
    } catch {
      return String(val)
    }
  }
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
  try {
    const { data } = await platformAdminApi.getCustomer(id)
    selected.value = data
    syncEditForm()
    activeEnvId.value = data.environments[0]?.id ?? null
    showList.value = false
    if (activeEnvId.value) await loadEnvPanel(activeEnvId.value)
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not open customer.')
  }
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
    selected.value = null
    showList.value = true
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
    const domain = provisionDomain.value.trim().toLowerCase()
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
      <header class="cust-head-bar">
        <UiPageHeader
          title="Customers"
          lede="Find accounts, confirm payments from Orders, and manage live hosting."
        />
        <div class="cust-head-actions">
          <form class="cust-search" @submit.prevent="loadList">
            <input v-model="q" type="search" placeholder="Search name, email, phone" />
            <button type="submit">Search</button>
          </form>
          <button type="button" class="btn-new-cust" @click="showAddCustomerModal = true">
            + Add Customer
          </button>
        </div>
      </header>

      <!-- Add Customer Modal -->
      <div v-if="showAddCustomerModal" class="cust-modal-backdrop" @click.self="showAddCustomerModal = false">
        <div class="cust-modal-card">
          <div class="modal-head">
            <h3>Add New Customer</h3>
            <button type="button" class="btn-close" @click="showAddCustomerModal = false">✕</button>
          </div>
          <p class="modal-sub">Create a customer account directly and optionally provision their initial hosting environment.</p>

          <UiAlert v-if="addCustError" tone="err">{{ addCustError }}</UiAlert>

          <form class="modal-form" @submit.prevent="submitCreateCustomer">
            <div class="form-group">
              <label>Full Name *</label>
              <input v-model="newCustFullName" required placeholder="e.g. John Doe" />
            </div>

            <div class="form-group">
              <label>Email Address *</label>
              <input v-model="newCustEmail" type="email" required placeholder="customer@example.com" />
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>Phone Number (optional)</label>
                <input v-model="newCustPhone" placeholder="+233..." />
              </div>
              <div class="form-group">
                <label>Company (optional)</label>
                <input v-model="newCustCompany" placeholder="Organization name" />
              </div>
            </div>

            <div class="form-group">
              <label>Password (optional, default auto-set)</label>
              <div class="ds-input-eye-wrap">
                <input
                  v-model="newCustPassword"
                  :type="showNewCustPassword ? 'text' : 'password'"
                  placeholder="Leave blank for WelcomePass2026!"
                />
                <button
                  type="button"
                  class="ds-eye-btn"
                  :title="showNewCustPassword ? 'Hide password' : 'Show password'"
                  tabindex="-1"
                  @click="showNewCustPassword = !showNewCustPassword"
                >
                  <IconEyeOff v-if="showNewCustPassword" :size="18" />
                  <IconEye v-else :size="18" />
                </button>
              </div>
            </div>

            <div class="form-section-title">Initial Hosting (Optional)</div>
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
                <label>Primary Domain</label>
                <input v-model="newCustDomain" placeholder="e.g. customerdomain.com" />
              </div>
            </div>

            <div class="modal-actions">
              <button type="button" class="btn-ghost" @click="showAddCustomerModal = false">Cancel</button>
              <button type="submit" class="btn-submit-cust" :disabled="addCustBusy">
                {{ addCustBusy ? 'Creating Customer…' : 'Create & Onboard Customer' }}
              </button>
            </div>
          </form>
        </div>
      </div>

      <!-- Edit Subdomain Modal (Hosting Operator & Owner Only) -->
      <div v-if="showEditSubdomainModal && activeEnv" class="cust-modal-backdrop" @click.self="showEditSubdomainModal = false">
        <div class="cust-modal-card">
          <div class="modal-head">
            <h3>Edit Personal Hosting Subdomain</h3>
            <button type="button" class="btn-close" @click="showEditSubdomainModal = false">✕</button>
          </div>
          <p class="modal-sub">
            Update the primary domain or custom subdomain for this hosting environment. Infrastructure and Nginx will be re-routed.
          </p>

          <UiAlert v-if="editSubdomainError" tone="err">{{ editSubdomainError }}</UiAlert>

          <form class="modal-form" @submit.prevent="submitEditSubdomain">
            <div class="form-group">
              <label>Domain or Subdomain *</label>
              <input
                v-model="newSubdomainDomain"
                required
                placeholder="e.g. john.ifnotus.space or mydomain.online"
                autofocus
              />
            </div>

            <div class="modal-actions">
              <button type="button" class="btn-ghost" :disabled="editSubdomainBusy" @click="showEditSubdomainModal = false">Cancel</button>
              <button type="submit" class="btn-submit-cust" :disabled="editSubdomainBusy">
                {{ editSubdomainBusy ? 'Updating Subdomain…' : 'Save Subdomain' }}
              </button>
            </div>
          </form>
        </div>
      </div>

      <p v-if="loading" class="cust-muted cust-status">Loading…</p>
      <UiAlert v-else-if="error" class="cust-status" tone="err">{{ error }}</UiAlert>

      <div v-else class="cust-layout">
        <aside class="cust-list" :class="{ 'is-hidden-mobile': selected && !showList }">
          <div class="list-filters">
            <button
              v-for="f in [
                { id: 'all' as const, label: `All (${statusCounts.all})` },
                { id: 'live' as const, label: `Live (${statusCounts.live})` },
                { id: 'awaiting_payment' as const, label: `Pay (${statusCounts.awaiting_payment})` },
                { id: 'setting_up' as const, label: `Setup (${statusCounts.setting_up})` },
                { id: 'none' as const, label: `None (${statusCounts.none})` },
              ]"
              :key="f.id"
              type="button"
              class="filter-chip"
              :class="{ on: statusFilter === f.id }"
              @click="statusFilter = f.id"
            >
              {{ f.label }}
            </button>
          </div>

          <div class="cust-table-wrap">
            <table class="cust-table">
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Status</th>
                  <th class="hide-sm">Hosting</th>
                  <th class="num">AI</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="c in filteredCustomers"
                  :key="c.id"
                  :class="{ on: selected?.customer.id === c.id }"
                  @click="openCustomer(c.id)"
                >
                  <td>
                    <p class="t-name">{{ c.full_name }}</p>
                    <p class="t-email">{{ c.email }}</p>
                    <p v-if="c.phone" class="t-meta">{{ c.phone }}</p>
                  </td>
                  <td>
                    <span class="status-pill" :data-s="c.hosting_status || 'none'">
                      {{ hostingStatusLabel(c.hosting_status) }}
                    </span>
                    <p v-if="c.awaiting_payment_count" class="t-meta warn">
                      {{ c.awaiting_payment_count }} payment(s)
                    </p>
                  </td>
                  <td class="hide-sm">
                    <p class="t-domain">{{ c.primary_domain || '—' }}</p>
                    <p class="t-meta">{{ c.environment_count }} env · {{ c.subscription_count }} sub</p>
                  </td>
                  <td class="num">{{ c.credits_remaining }}</td>
                </tr>
                <tr v-if="!filteredCustomers.length">
                  <td colspan="4" class="cust-empty">No customers match.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </aside>

        <section class="cust-detail" :class="{ 'is-hidden-mobile': !selected || showList }">
          <UiAlert v-if="msg" :tone="msg.toLowerCase().includes('could not') || msg.toLowerCase().includes('type ') ? 'err' : 'ok'">{{ msg }}</UiAlert>
          <p v-if="!selected" class="cust-muted pick-hint">Select a customer from the list.</p>

          <template v-else>
            <button type="button" class="cust-back" @click="showList = true">← Customers</button>

            <div class="card">
              <div class="card-top">
                <div class="min0">
                  <h2 class="title" :title="selected.customer.full_name">{{ selected.customer.full_name }}</h2>
                  <p class="email-line" :title="selected.customer.email">{{ selected.customer.email }}</p>
                </div>
                <div class="chips">
                  <span class="chip">{{ selected.customer.email_verified ? 'Verified' : 'Unverified' }}</span>
                  <span class="chip">2FA {{ selected.customer.two_factor_enabled ? 'on' : 'off' }}</span>
                  <span class="chip">{{ selected.credits_remaining }} AI credits</span>
                </div>
              </div>
              <p v-if="!canEditProfile && (selected.customer.phone || selected.customer.company)" class="submeta">
                <span v-if="selected.customer.phone">{{ selected.customer.phone }}</span>
                <span v-if="selected.customer.phone && selected.customer.company"> · </span>
                <span v-if="selected.customer.company">{{ selected.customer.company }}</span>
              </p>

              <div v-if="canEditProfile" class="provision profile-edit">
                <h3>Contact details</h3>
                <p class="cust-muted">
                  Update login email or phone. Changing the phone marks it verified so SMS login works immediately.
                </p>
                <div class="profile-grid">
                  <label class="profile-field">
                    <span>Email</span>
                    <input v-model="editEmail" type="email" autocomplete="off" />
                  </label>
                  <label class="profile-field">
                    <span>Phone</span>
                    <input v-model="editPhone" type="tel" autocomplete="off" placeholder="0248069639" />
                  </label>
                  <label class="profile-field">
                    <span>First name</span>
                    <input v-model="editFirst" type="text" autocomplete="off" />
                  </label>
                  <label class="profile-field">
                    <span>Last name</span>
                    <input v-model="editLast" type="text" autocomplete="off" />
                  </label>
                  <label class="profile-field profile-field-wide">
                    <span>Company</span>
                    <input v-model="editCompany" type="text" autocomplete="off" />
                  </label>
                </div>
                <div class="provision-row">
                  <button type="button" class="btn primary" :disabled="profileBusy" @click="saveCustomerProfile">
                    {{ profileBusy ? 'Saving…' : 'Save contact details' }}
                  </button>
                  <span v-if="selected.customer.phone_verified" class="cust-muted">Phone verified</span>
                  <span v-else class="cust-muted warn">Phone not verified</span>
                </div>
              </div>

              <div v-if="canDelete" class="provision danger-zone danger-zone-top">
                <h3>Remove account</h3>
                <p class="cust-muted">
                  Permanently deletes this tenant — login, hosting environments, orders, and on-disk files.
                  Type their email to confirm.
                </p>
                <div class="provision-row">
                  <input
                    v-model="deleteConfirmEmail"
                    type="email"
                    :placeholder="selected.customer.email"
                    autocomplete="off"
                  />
                  <button
                    type="button"
                    class="btn-danger"
                    :disabled="deleteBusy || busy || !deleteConfirmEmail.trim()"
                    @click="deleteCustomer"
                  >
                    {{ deleteBusy ? 'Removing…' : 'Remove account' }}
                  </button>
                </div>
              </div>

              <div class="split">
                <div class="min0">
                  <h3>Subscriptions</h3>
                  <ul class="stack-list">
                    <li v-for="s in selected.subscriptions" :key="s.id" class="mini-card">
                      <p class="mini-title" :title="s.plan_name || s.plan_id">{{ s.plan_name || s.plan_id }}</p>
                      <p class="mini-meta">{{ s.status }}</p>
                      <p class="mini-meta wrap">
                        {{ s.cpu_allocated }} vCPU · {{ s.ram_allocated }} GB · {{ s.storage_allocated }} GB
                        <span v-if="s.expires_at"> · exp {{ new Date(s.expires_at).toLocaleDateString() }}</span>
                        <span v-if="s.auto_renew"> · auto-renew</span>
                      </p>
                    </li>
                    <li v-if="!selected.subscriptions.length" class="cust-muted">None</li>
                  </ul>
                </div>
                <div class="min0">
                  <h3>Recent orders</h3>
                  <ul class="stack-list">
                    <li v-for="o in selected.orders.slice(0, 6)" :key="o.id" class="mini-card">
                      <p class="mini-title" :title="o.plan_name || o.plan_id">{{ o.plan_name || o.plan_id }}</p>
                      <p class="mini-meta wrap">
                        {{ o.payment_status }} / {{ o.provisioning_status }} · {{ o.currency }} {{ o.total_price }}
                      </p>
                    </li>
                    <li v-if="!selected.orders.length" class="cust-muted">None</li>
                  </ul>
                </div>
              </div>

              <div v-if="canGrantCredits" class="provision grant-credits">
                <h3>Give AI credits</h3>
                <p class="cust-muted">
                  Super admin or hosting can add credits manually (no invoice). Client sees the new balance in Billing / Dev Companion.
                </p>
                <div class="provision-row">
                  <input
                    v-model.number="grantCredits"
                    type="number"
                    min="1"
                    max="100000"
                    step="1"
                    placeholder="Credits"
                    aria-label="Credits to grant"
                  />
                  <input
                    v-model="grantNote"
                    placeholder="Optional note e.g. goodwill / support"
                  />
                  <button
                    type="button"
                    class="btn-primary"
                    :disabled="grantBusy || busy || !grantCredits || grantCredits < 1"
                    @click="grantCreditsToCustomer"
                  >
                    {{ grantBusy ? 'Adding…' : 'Add credits' }}
                  </button>
                </div>
                <p class="mini-meta">Current balance: {{ selected.credits_remaining }} credits</p>
              </div>

              <div v-if="canProvision" class="provision">
                <h3>Activate hosting</h3>
                <p class="cust-muted">
                  Super admin only — for goodwill / demo accounts without MoMo.
                  Prefer <strong>Orders → Confirm &amp; activate</strong> for paid invoices.
                </p>
                <div class="provision-row">
                  <select v-model="provisionPlanId">
                    <option v-for="p in allPlans" :key="p.id" :value="p.id">
                      {{ p.name }} — GHS {{ p.price_monthly }}
                    </option>
                  </select>
                  <input
                    v-model="provisionDomain"
                    placeholder="Optional domain e.g. studio.online"
                  />
                  <button
                    type="button"
                    class="btn-primary"
                    :disabled="busy || !provisionPlanId"
                    @click="provisionHosting"
                  >
                    {{ busy ? 'Activating…' : 'Activate' }}
                  </button>
                </div>
              </div>
            </div>

            <div class="env-layout">
              <div class="card env-picker">
                <h3>Environments</h3>
                <ul>
                  <li v-for="env in selected.environments" :key="env.id">
                    <button
                      type="button"
                      class="env-item"
                      :class="{ on: activeEnvId === env.id }"
                      @click="selectEnv(env.id)"
                    >
                      <span class="env-domain" :title="env.domain || env.id">{{ envHeadline(env) }}</span>
                      <span class="env-meta">{{ env.status }} · {{ env.health_status }}</span>
                      <span class="env-stack" :title="stackLabel(env)">{{ stackLabel(env) }}</span>
                    </button>
                  </li>
                  <li v-if="!selected.environments.length" class="cust-empty">No environments.</li>
                </ul>
              </div>

              <div v-if="activeEnv" class="card env-panel min0">
                <div class="env-head">
                  <div class="min0">
                    <h3 class="env-title" :title="activeEnv.domain || activeEnv.id">
                      {{ envHeadline(activeEnv) }}
                    </h3>
                    <p v-if="activeEnv.hosting_name && activeEnv.domain" class="env-sub">
                      {{ activeEnv.domain }}
                    </p>
                    <p class="env-tech muted">Environment ID {{ activeEnv.id }}</p>
                    <div class="chips tight">
                      <span class="chip">{{ activeEnv.status }}</span>
                      <span class="chip">health {{ activeEnv.health_status }}</span>
                      <span class="chip">{{ activeEnv.cpu_limit }} vCPU</span>
                      <span class="chip">{{ activeEnv.ram_limit_gb }} GB RAM</span>
                      <span class="chip">{{ activeEnv.storage_limit_gb }} GB disk</span>
                      <span v-if="activeEnv.db_name" class="chip" :title="`${activeEnv.db_engine}:${activeEnv.db_name}`">
                        {{ activeEnv.db_engine }}:{{ activeEnv.db_name }}
                      </span>
                      <span v-if="activeEnv.ftp_username" class="chip">FTP {{ activeEnv.ftp_username }}</span>
                    </div>
                    <p class="env-stack-line" :title="stackLabel(activeEnv)">{{ stackLabel(activeEnv) }}</p>
                    <p
                      v-if="activeEnv.document_root"
                      class="path"
                      :title="activeEnv.document_root"
                    >{{ activeEnv.document_root }}</p>
                    <p v-if="activeEnv.created_at" class="cust-muted">
                      Created {{ new Date(activeEnv.created_at).toLocaleString() }}
                    </p>
                  </div>
                </div>

                <div v-if="canOps" class="actions">
                  <button
                    v-if="canEditSubdomain && activeEnv.status !== 'terminated'"
                    type="button"
                    class="btn"
                    :disabled="busy"
                    @click="openEditSubdomainModal(activeEnv)"
                  >
                    Edit Subdomain
                  </button>
                  <button type="button" class="btn" :disabled="busy" @click="runHealth">Live health</button>
                  <button type="button" class="btn" :disabled="busy" @click="loadLogs">Logs</button>
                  <button type="button" class="btn" :disabled="busy" @click="repairFs(activeEnv.id)">Repair permissions</button>
                  <button
                    type="button"
                    class="btn warn"
                    :disabled="busy || activeEnv.status === 'terminated'"
                    @click="clearEnvStack(activeEnv.id, activeEnv.domain)"
                  >
                    Clear install
                  </button>
                  <button
                    v-if="activeEnv.status !== 'suspended' && activeEnv.status !== 'terminated'"
                    type="button"
                    class="btn"
                    :disabled="busy"
                    @click="suspendEnv(activeEnv.id)"
                  >
                    Suspend
                  </button>
                  <button
                    v-if="activeEnv.status === 'suspended'"
                    type="button"
                    class="btn ok"
                    :disabled="busy"
                    @click="restoreEnv(activeEnv.id)"
                  >
                    Restore
                  </button>
                  <button
                    v-if="canTerminate && activeEnv.status !== 'terminated'"
                    type="button"
                    class="btn danger"
                    :disabled="busy"
                    @click="terminateEnv(activeEnv.id, activeEnv.domain)"
                  >
                    Terminate
                  </button>
                </div>

                <UiTabBar
                  :items="envTabs"
                  :model-value="envTab"
                  variant="flat"
                  aria-label="Environment detail"
                  @update:model-value="envTab = $event as typeof envTab"
                />

                <div v-if="envTab === 'overview'" class="tab-body">
                  <p v-if="usage" class="wrap">
                    Storage
                    <strong>{{ usage.storage_used_gb.toFixed(2) }}</strong>
                    / {{ usage.storage_limit_gb }} GB ({{ usage.storage_pct.toFixed(0) }}%) ·
                    {{ usage.file_count }} files · {{ usage.storage_status }}
                  </p>
                  <p v-if="usage?.hard_exceeded" class="cust-err">Disk hard limit exceeded — suspend if they threaten the host.</p>
                  <p v-else-if="usage?.soft_warning" class="cust-warn">Disk soft warning — ask them to clean up or upgrade.</p>
                  <p v-if="usage?.message" class="cust-muted wrap">{{ usage.message }}</p>
                  <p class="cust-muted wrap">
                    Isolation {{ activeEnv.isolation_type }}
                    <span v-if="activeEnv.container_id"> · container {{ activeEnv.container_id.slice(0, 12) }}</span>
                  </p>
                </div>

                <div v-else-if="envTab === 'health'" class="tab-body">
                  <p v-if="!health" class="cust-muted">Run Live health to probe HTTP, docroot, and isolation.</p>
                  <template v-else>
                    <p class="wrap"><strong>{{ health.health_status }}</strong> — {{ health.summary }}</p>
                    <ul class="checks">
                      <li v-for="(val, key) in health.checks" :key="String(key)">
                        <span class="check-key">{{ key }}</span>
                        <span class="check-val">{{ checkValue(val) }}</span>
                      </li>
                    </ul>
                  </template>
                </div>

                <div v-else-if="envTab === 'stacks'" class="tab-body">
                  <p>Current: <strong>{{ currentStackName() }}</strong></p>
                  <pre v-if="stacks?.progress" class="progress-box">{{ JSON.stringify(stacks.progress, null, 2) }}</pre>
                  <div v-if="canOps" class="install-row">
                    <label>
                      Install stack
                      <select v-model="installStackId">
                        <option
                          v-for="s in stacks?.stacks || []"
                          :key="s.id"
                          :value="s.id"
                          :disabled="s.allowed === false"
                        >
                          {{ s.name }}
                        </option>
                      </select>
                    </label>
                    <button type="button" class="btn-primary" :disabled="busy" @click="installStack">Install</button>
                  </div>
                </div>

                <div v-else-if="envTab === 'logs'" class="tab-body">
                  <p v-if="!logs" class="cust-muted">Click Logs to load nginx/app output for this tenant only.</p>
                  <div v-else class="log-box">
                    <p v-for="(line, i) in logs.entries" :key="i">
                      <span class="log-src">[{{ line.source }}]</span> {{ line.message }}
                    </p>
                    <p v-if="!logs.entries.length" class="cust-muted">{{ logs.message || 'No log lines.' }}</p>
                  </div>
                </div>

                <div v-else class="tab-body">
                  <ul class="audit">
                    <li v-for="a in envAuditRows" :key="a.id">
                      <span class="when">{{ new Date(a.occurred_at).toLocaleString() }}</span>
                      <span class="wrap">{{ a.action }} · {{ a.result }}</span>
                    </li>
                    <li v-if="!envAuditRows.length" class="cust-muted">No audit events yet.</li>
                  </ul>
                </div>
              </div>
            </div>

            <div class="card">
              <h3>Customer activity</h3>
              <ul class="audit">
                <li v-for="a in auditRows" :key="a.id">
                  <span class="when">{{ new Date(a.occurred_at).toLocaleString() }}</span>
                  <span class="wrap">
                    <strong>{{ a.action }}</strong>
                    <template v-if="a.target_type"> · {{ a.target_type }}</template>
                    · {{ a.result }}
                  </span>
                </li>
                <li v-if="!auditRows.length" class="cust-muted">No activity recorded.</li>
              </ul>
            </div>
          </template>
        </section>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.cust {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  min-height: 0;
  box-sizing: border-box;
  padding: 1.15rem clamp(1.35rem, 3vw, 2.5rem) 1.75rem;
  gap: 0.85rem;
}

.cust-head-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.85rem 1.25rem;
  padding: 0 0 0.85rem;
  border-bottom: 1px solid #e2e8f0;
  background: transparent;
  flex-shrink: 0;
}
.dark .cust-head-bar {
  border-bottom-color: #334155;
}
.cust-head-bar :deep(.ui-page-header) {
  margin: 0;
}
.cust-head-bar :deep(h1) {
  font-size: 1.15rem;
}

.cust-head-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}

.btn-new-cust {
  background: #1e3a5f;
  color: #fff;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  font-weight: 600;
  font-size: 0.85rem;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}

.btn-new-cust:hover {
  background: #2b5182;
}

.cust-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(2px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
}

.cust-modal-card {
  background: #fff;
  border-radius: 0.85rem;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
  width: 100%;
  max-width: 32rem;
  padding: 1.75rem;
  color: #1e293b;
  max-height: 90vh;
  overflow-y: auto;
}

.dark .cust-modal-card {
  background: #0f172a;
  color: #f1f5f9;
  border: 1px solid #334155;
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.25rem;
}

.modal-head h3 {
  font-size: 1.25rem;
  font-weight: 700;
  margin: 0;
}

.btn-close {
  background: transparent;
  border: none;
  font-size: 1.1rem;
  cursor: pointer;
  color: #64748b;
}

.modal-sub {
  font-size: 0.85rem;
  color: #64748b;
  margin-bottom: 1.25rem;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  flex: 1;
}

.form-group label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #475569;
}

.dark .form-group label {
  color: #94a3b8;
}

.form-group input,
.form-group select {
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  background: #fff;
  color: inherit;
}

.dark .form-group input,
.dark .form-group select {
  background: #1e293b;
  border-color: #334155;
}

.form-row {
  display: flex;
  gap: 0.75rem;
}

.form-section-title {
  font-size: 0.85rem;
  font-weight: 700;
  color: #1e3a5f;
  border-top: 1px solid #e2e8f0;
  padding-top: 0.75rem;
  margin-top: 0.25rem;
}

.dark .form-section-title {
  color: #38bdf8;
  border-top-color: #334155;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.btn-submit-cust {
  background: #0284c7;
  color: #fff;
  border: none;
  padding: 0.55rem 1.25rem;
  border-radius: 0.5rem;
  font-weight: 600;
  font-size: 0.875rem;
  cursor: pointer;
}

.btn-submit-cust:hover {
  background: #0369a1;
}

.btn-submit-cust:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.cust-search {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  width: 100%;
  flex: 1 1 18rem;
  max-width: 36rem;
}
.cust-search input,
.cust-search button,
.provision-row select,
.provision-row input,
.install-row select {
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  padding: 0.45rem 0.7rem;
  font-size: 0.875rem;
  background: #fff;
  color: inherit;
  min-width: 0;
}
.dark .cust-search input,
.dark .cust-search button,
.dark .provision-row select,
.dark .provision-row input,
.dark .install-row select,
.dark .card,
.dark .mini-card,
.dark .cust-toast {
  background: #0f172a;
  border-color: #334155;
}
.cust-search input { flex: 1 1 10rem; }
.cust-search button {
  cursor: pointer;
  white-space: nowrap;
}

.cust-layout {
  flex: 1 1 auto;
  display: grid;
  gap: 0;
  grid-template-columns: minmax(0, 1fr);
  align-items: stretch;
  min-width: 0;
  min-height: 0;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.dark .cust-layout {
  border-color: #334155;
  background: #0f172a;
}
@media (min-width: 1100px) {
  .cust-layout {
    grid-template-columns: minmax(22rem, 30rem) minmax(0, 1fr);
  }
  .cust-back { display: none !important; }
  .cust-list.is-hidden-mobile,
  .cust-detail.is-hidden-mobile { display: flex !important; }
}
@media (min-width: 1400px) {
  .cust-layout {
    grid-template-columns: minmax(24rem, 34rem) minmax(0, 1fr);
  }
}
@media (max-width: 1099px) {
  .cust-list.is-hidden-mobile { display: none; }
  .cust-detail.is-hidden-mobile { display: none; }
}

.cust-list,
.cust-detail {
  min-width: 0;
  max-width: none;
}
.cust-list {
  display: flex;
  flex-direction: column;
  border: none;
  border-radius: 0;
  border-right: 1px solid #e2e8f0;
  background: #fff;
  overflow: hidden;
  min-height: 0;
}
.dark .cust-list {
  border-right-color: #334155;
  background: #0f172a;
}
.cust-detail {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 0;
  overflow: auto;
  padding: 1.15rem 1.35rem 1.65rem;
  background: var(--if-paper, #f8fafc);
}
.dark .cust-detail {
  background: #0b1120;
}

.list-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  padding: 0.75rem 0.85rem;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}
.dark .list-filters {
  background: #1e293b;
  border-bottom-color: #334155;
}
.filter-chip {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #fff;
  color: #475569;
  font-size: 0.7rem;
  font-weight: 650;
  padding: 0.28rem 0.65rem;
  cursor: pointer;
}
.filter-chip.on {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}
.dark .filter-chip {
  background: #0f172a;
  border-color: #475569;
  color: #cbd5e1;
}
.dark .filter-chip.on {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}

.cust-status {
  padding: 0;
}

.cust-table-wrap {
  flex: 1 1 auto;
  overflow: auto;
  min-height: 0;
  max-height: none;
}
.cust-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.cust-table th {
  text-align: left;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
  font-weight: 700;
  padding: 0.55rem 0.85rem;
  border-bottom: 1px solid #e2e8f0;
  position: sticky;
  top: 0;
  background: #fff;
  z-index: 1;
}
.dark .cust-table th {
  background: #0f172a;
  border-bottom-color: #334155;
}
.cust-table td {
  padding: 0.7rem 0.85rem;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: top;
}
.dark .cust-table td { border-bottom-color: #1e293b; }
.cust-table tbody tr {
  cursor: pointer;
  transition: background 0.12s ease;
}
.cust-table tbody tr:hover,
.cust-table tbody tr.on { background: #f8fafc; }
.dark .cust-table tbody tr:hover,
.dark .cust-table tbody tr.on { background: #1e293b; }
.cust-table .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: #334155;
}
.t-name {
  margin: 0;
  font-weight: 650;
  color: #0f172a;
  font-size: 0.9rem;
}
.dark .t-name { color: #f8fafc; }
.t-email,
.t-meta,
.t-domain {
  margin: 0.15rem 0 0;
  font-size: 0.75rem;
  color: #64748b;
  overflow-wrap: anywhere;
}
.t-domain { color: #334155; font-weight: 500; }
.dark .t-domain { color: #cbd5e1; }
.t-meta.warn { color: #b45309; font-weight: 600; }
.status-pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.15rem 0.5rem;
  font-size: 0.68rem;
  font-weight: 700;
  background: #f1f5f9;
  color: #334155;
  white-space: nowrap;
}
.status-pill[data-s='live'] { background: #d1fae5; color: #065f46; }
.status-pill[data-s='awaiting_payment'] { background: #fef3c7; color: #92400e; }
.status-pill[data-s='setting_up'] { background: #ffedd5; color: #9a3412; }
.status-pill[data-s='suspended'] { background: #fee2e2; color: #991b1b; }
.status-pill[data-s='none'],
.status-pill[data-s='inactive'] { background: #e2e8f0; color: #475569; }
@media (max-width: 640px) {
  .hide-sm { display: none; }
}
.pick-hint {
  padding: 2rem 1rem;
  text-align: center;
  border: 1px dashed #cbd5e1;
  border-radius: 0.85rem;
}
.danger-zone {
  border-color: #fecaca !important;
  background: #fff7f7;
}
.dark .danger-zone {
  background: rgba(127, 29, 29, 0.15);
  border-color: #7f1d1d !important;
}
.btn-danger {
  border: 0;
  border-radius: 0.5rem;
  background: #dc2626;
  color: #fff;
  font-size: 0.85rem;
  font-weight: 650;
  padding: 0.45rem 0.85rem;
  cursor: pointer;
  white-space: nowrap;
}
.btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }

.title,
.email-line,
.env-domain,
.env-title,
.env-stack,
.env-stack-line,
.mini-title,
.path,
.wrap,
.check-val,
.log-box p {
  overflow-wrap: anywhere;
  word-break: break-word;
}
.title,
.env-domain,
.env-title,
.mini-title,
.email-line {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cust-back {
  align-self: flex-start;
  border: 0;
  background: transparent;
  color: #1e3a5f;
  font-size: 0.85rem;
  font-weight: 650;
  cursor: pointer;
  padding: 0;
}
.cust-toast {
  margin: 0;
  padding: 0.65rem 0.85rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  background: #fff;
  font-size: 0.875rem;
  overflow-wrap: anywhere;
}
.cust-muted { margin: 0; font-size: 0.84rem; color: #64748b; }
.cust-err { margin: 0; font-size: 0.84rem; color: #b42318; }
.cust-warn { margin: 0; font-size: 0.84rem; color: #b54708; }
.cust-empty { padding: 1rem; font-size: 0.875rem; color: #64748b; text-align: center; }

.card {
  border: 1px solid #e2e8f0;
  border-radius: 0.85rem;
  background: #fff;
  padding: 1rem;
  overflow: hidden;
}
.dark .card { border-color: #334155; }
.card-top {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}
.min0 { min-width: 0; }
.title { margin: 0; font-size: 1.1rem; font-weight: 650; max-width: 100%; }
.email-line { margin: 0.2rem 0 0; font-size: 0.8rem; color: #64748b; max-width: 100%; }
.submeta { margin: 0.45rem 0 0; font-size: 0.8rem; color: #64748b; overflow-wrap: anywhere; }

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  max-width: 100%;
}
.chips.tight { margin-top: 0.55rem; }
.chip {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0.18rem 0.55rem;
  border-radius: 999px;
  background: #f1f5f9;
  color: #334155;
  font-size: 0.72rem;
  font-weight: 650;
}
.dark .chip { background: #1e293b; color: #cbd5e1; }

.split {
  display: grid;
  gap: 1rem;
  margin-top: 1rem;
  grid-template-columns: minmax(0, 1fr);
}
@media (min-width: 720px) {
  .split { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
h3 {
  margin: 0 0 0.55rem;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: #64748b;
}
.stack-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.mini-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  padding: 0.55rem 0.7rem;
  min-width: 0;
  overflow: hidden;
}
.dark .mini-card { border-color: #334155; }
.mini-title { margin: 0; font-size: 0.88rem; font-weight: 650; }
.mini-meta { margin: 0.2rem 0 0; font-size: 0.78rem; color: #64748b; }

.provision {
  margin-top: 1rem;
  padding-top: 0.85rem;
  border-top: 1px solid #e2e8f0;
}
.dark .provision { border-top-color: #334155; }
.provision-row,
.install-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.55rem;
  align-items: flex-end;
}
.provision-row select,
.provision-row input { flex: 1 1 10rem; max-width: 100%; }

.profile-grid {
  display: grid;
  gap: 0.65rem;
  margin-top: 0.55rem;
  grid-template-columns: minmax(0, 1fr);
}
@media (min-width: 640px) {
  .profile-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.profile-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.78rem;
  color: #64748b;
}
.profile-field-wide { grid-column: 1 / -1; }
.profile-field input {
  width: 100%;
  padding: 0.45rem 0.55rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  font-size: 0.88rem;
  color: inherit;
  background: #fff;
}
.dark .profile-field input {
  background: #0f172a;
  border-color: #334155;
}

.env-layout {
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(0, 1fr);
  width: 100%;
}
@media (min-width: 900px) {
  .env-layout {
    grid-template-columns: minmax(13rem, 16rem) minmax(0, 1fr);
    align-items: start;
  }
}
.env-picker ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.env-item {
  width: 100%;
  text-align: left;
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  background: transparent;
  padding: 0.55rem 0.65rem;
  cursor: pointer;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.dark .env-item { border-color: #334155; }
.env-item.on,
.env-item:hover {
  border-color: #94a3b8;
  background: #f8fafc;
}
.dark .env-item.on,
.dark .env-item:hover { background: #1e293b; }
.env-meta,
.env-stack { font-size: 0.72rem; color: #64748b; }
.env-stack {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-title { margin: 0; font-size: 1.05rem; font-weight: 650; }
.env-sub { margin: 0.2rem 0 0; font-size: 0.86rem; color: #5c6670; }
.env-tech { margin: 0.35rem 0 0; font-size: 0.72rem; font-family: ui-monospace, monospace; word-break: break-all; }
.env-stack-line { margin: 0.45rem 0 0; font-size: 0.8rem; color: #64748b; }
.path {
  margin: 0.35rem 0 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.7rem;
  color: #94a3b8;
  line-height: 1.35;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.85rem;
}
.btn,
.btn-primary {
  border: 1px solid #cbd5e1;
  border-radius: 0.45rem;
  background: #fff;
  padding: 0.35rem 0.65rem;
  font-size: 0.75rem;
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
}
.dark .btn { background: #0f172a; border-color: #475569; color: #e2e8f0; }
.btn:disabled,
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.warn { border-color: #f59e0b; color: #92400e; }
.btn.ok { border-color: #34d399; color: #065f46; }
.btn.danger { border-color: #f87171; color: #b91c1c; }
.btn-primary {
  border: 0;
  background: #1e3a5f;
  color: #fff;
}

.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.9rem;
  padding-bottom: 0.65rem;
  border-bottom: 1px solid #e2e8f0;
}
.dark .tabs { border-bottom-color: #334155; }
.tabs button {
  border: 0;
  background: transparent;
  border-radius: 0.4rem;
  padding: 0.3rem 0.55rem;
  font-size: 0.75rem;
  font-weight: 650;
  color: #64748b;
  cursor: pointer;
}
.tabs button.on {
  background: #0f172a;
  color: #fff;
}
.dark .tabs button.on {
  background: #f8fafc;
  color: #0f172a;
}

.tab-body {
  margin-top: 0.85rem;
  font-size: 0.875rem;
  min-width: 0;
}
.checks {
  list-style: none;
  margin: 0.55rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.checks li {
  display: grid;
  grid-template-columns: minmax(5rem, 8rem) minmax(0, 1fr);
  gap: 0.5rem;
  font-size: 0.78rem;
}
@media (max-width: 520px) {
  .checks li { grid-template-columns: minmax(0, 1fr); }
}
.check-key { font-weight: 650; color: #475569; }
.check-val {
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  overflow-wrap: anywhere;
}
.progress-box,
.log-box {
  margin: 0.55rem 0 0;
  max-height: 16rem;
  overflow: auto;
  border-radius: 0.55rem;
  background: #020617;
  color: #e2e8f0;
  padding: 0.65rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.7rem;
  line-height: 1.4;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.log-box p { margin: 0 0 0.25rem; }
.log-src { color: #94a3b8; }
.install-row label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: #64748b;
  min-width: 0;
  flex: 1 1 12rem;
}
.audit {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 14rem;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.audit li {
  display: grid;
  grid-template-columns: minmax(7rem, 9.5rem) minmax(0, 1fr);
  gap: 0.5rem;
  font-size: 0.75rem;
  color: #475569;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid #f1f5f9;
}
.dark .audit li { border-bottom-color: #1e293b; color: #94a3b8; }
@media (max-width: 560px) {
  .audit li { grid-template-columns: minmax(0, 1fr); }
}
.when { color: #94a3b8; white-space: nowrap; }
</style>
