<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { CustomerDashboard, HostingPlan } from '@/types/platform'
import { customersApi } from '@/api'
import { openHostingFromAccount } from '@/lib/hostingDeepLink'
import { getApiErrorMessage } from '@/lib/apiError'
import IconEye from '@/components/icons/IconEye.vue'
import IconEyeOff from '@/components/icons/IconEyeOff.vue'

const props = defineProps<{
  dash: CustomerDashboard
  plans: HostingPlan[]
}>()

const emit = defineEmits<{
  openPanel: [string]
  refresh: []
}>()

const router = useRouter()

// View state: 'list' or 'details'
const selectedEnvId = ref<string | null>(null)
const activeTab = ref<'details' | 'domains' | 'nameservers' | 'password'>('details')

// Customer domains tab state
const customerDomains = ref<
  Array<{
    id: string
    domain_name: string
    status: string
    is_active: boolean
    registration_date?: string | null
    expiry_date?: string | null
    environment_domain?: string | null
    propagation_notice?: string
  }>
>([])
const domainsLoading = ref(false)
const searchDomName = ref('')
const searchDomExt = ref('.online')
const searchDomBusy = ref(false)
const searchDomResult = ref<{
  domain: string
  available: boolean
  price_yearly: number
  message: string
} | null>(null)
const domainOrderBusy = ref(false)
const domainOrderMsg = ref('')
const domainOrderSuccess = ref(false)

async function loadCustomerDomains() {
  domainsLoading.value = true
  try {
    const { data } = await customersApi.listDomains()
    customerDomains.value = data.items || []
  } catch {
    /* fallback */
  } finally {
    domainsLoading.value = false
  }
}

async function checkDomainAvailability() {
  const name = searchDomName.value.trim().toLowerCase()
  if (!name) return
  searchDomBusy.value = true
  searchDomResult.value = null
  domainOrderMsg.value = ''
  try {
    const { data } = await customersApi.checkDomain(name, searchDomExt.value)
    searchDomResult.value = data
  } catch (e) {
    domainOrderMsg.value = getApiErrorMessage(e, 'Could not check domain availability.')
  } finally {
    searchDomBusy.value = false
  }
}

async function orderStandaloneDomain() {
  if (!searchDomResult.value?.available) return
  domainOrderBusy.value = true
  domainOrderMsg.value = ''
  domainOrderSuccess.value = false
  try {
    const { data } = await customersApi.orderDomain({
      domain_name: searchDomName.value.trim().toLowerCase(),
      domain_extension: searchDomExt.value,
      environment_id: selectedService.value?.env.id || undefined,
    })
    domainOrderSuccess.value = true
    domainOrderMsg.value = `Order placed (Invoice #${data.invoice_number || data.order.id.slice(0, 8)}). Note: New domain registrations and DNS updates take 24 to 48 hours to fully propagate worldwide across all networks. We will send you an SMS once activated.`
    searchDomResult.value = null
    searchDomName.value = ''
    await loadCustomerDomains()
  } catch (e) {
    domainOrderMsg.value = getApiErrorMessage(e, 'Could not place domain order.')
  } finally {
    domainOrderBusy.value = false
  }
}

// List table state
const searchQuery = ref('')
const entriesPerPage = ref(10)
const currentPage = ref(1)

// Password tab state
const newPassword = ref('')
const confirmPassword = ref('')
const showNewPassword = ref(false)
const passwordBusy = ref(false)
const passwordMsg = ref('')
const passwordMsgType = ref<'success' | 'error'>('success')
const showDetailsPass = ref(false)

// Upgrade modal state
const showUpgradeModal = ref(false)
const selectedUpgradePlanId = ref('')
const upgradeBusy = ref(false)
const upgradeMsg = ref('')

// Cancel modal state
const showCancelModal = ref(false)
const cancelReason = ref('No longer needed')
const cancelDetails = ref('')
const cancelBusy = ref(false)
const cancelMsg = ref('')

// Notification / banner feedback
const actionMsg = ref('')
const actionMsgType = ref<'success' | 'error'>('success')

// Map environments with their subscription and plan data
const serviceItems = computed(() => {
  const envs = props.dash.environments || []
  const subs = props.dash.subscriptions || []

  return envs.map((env) => {
    const sub = subs.find((s) => s.id === env.subscription_id) || subs[0]
    const plan = props.plans.find((p) => p.id === sub?.plan_id) || null
    return {
      env,
      sub,
      plan,
      domain: env.domain || 'Unassigned Domain',
      username: env.hosting_name || 'ifn_' + env.id.slice(0, 6),
      status: env.status || sub?.status || 'active',
      planName: plan?.name || 'Personal Hosting',
      price: sub ? Number(plan?.price_monthly || 25) : 25,
      currency: plan?.currency || 'GH₵',
      billingTerm: sub?.billing_term_months || 1,
      expiresAt: sub?.expires_at,
      createdAt: env.created_at || null,
      idShort: sub ? sub.id.slice(0, 8).toUpperCase() : env.id.slice(0, 8).toUpperCase(),
    }
  })
})

const filteredServices = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return serviceItems.value
  return serviceItems.value.filter(
    (s) =>
      s.domain.toLowerCase().includes(q) ||
      s.username.toLowerCase().includes(q) ||
      s.planName.toLowerCase().includes(q) ||
      s.status.toLowerCase().includes(q),
  )
})

const totalItems = computed(() => filteredServices.value.length)
const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / entriesPerPage.value)))
const paginatedServices = computed(() => {
  const start = (currentPage.value - 1) * entriesPerPage.value
  return filteredServices.value.slice(start, start + entriesPerPage.value)
})

const selectedService = computed(() => {
  if (!selectedEnvId.value) return null
  return serviceItems.value.find((s) => s.env.id === selectedEnvId.value) || null
})

function selectService(envId: string) {
  selectedEnvId.value = envId
  activeTab.value = 'details'
  passwordMsg.value = ''
  newPassword.value = ''
  confirmPassword.value = ''
  void loadCustomerDomains()
}

function backToList() {
  selectedEnvId.value = null
  passwordMsg.value = ''
  actionMsg.value = ''
}

function billingCycleText(months: number) {
  if (months === 1) return 'Every month'
  if (months === 3) return 'Every 3 months'
  if (months === 6) return 'Every 6 months'
  if (months === 12) return 'Every year'
  return `Every ${months} months`
}

function formatDate(iso?: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

function formatDateTime(iso?: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

function daysUntil(iso?: string | null) {
  if (!iso) return 0
  const diff = new Date(iso).getTime() - Date.now()
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)))
}

function launchFpanel(domain: string, envId: string) {
  openHostingFromAccount(domain, 'overview', envId)
}

function generatePassword() {
  const chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%^&*'
  let pwd = ''
  for (let i = 0; i < 14; i++) {
    pwd += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  newPassword.value = pwd
  confirmPassword.value = pwd
}

async function saveHostingPassword() {
  if (!selectedService.value) return
  if (!newPassword.value) {
    passwordMsg.value = 'Please enter a password.'
    passwordMsgType.value = 'error'
    return
  }
  if (newPassword.value.length < 8) {
    passwordMsg.value = 'Password must be at least 8 characters long.'
    passwordMsgType.value = 'error'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    passwordMsg.value = 'Passwords do not match.'
    passwordMsgType.value = 'error'
    return
  }

  passwordBusy.value = true
  passwordMsg.value = ''
  try {
    const { data } = await customersApi.setHostingPassword(
      selectedService.value.env.id,
      newPassword.value,
    )
    passwordMsg.value = data.message || 'Hosting fPanel password updated successfully!'
    passwordMsgType.value = 'success'
    newPassword.value = ''
    confirmPassword.value = ''
  } catch (err: unknown) {
    passwordMsg.value = getApiErrorMessage(err, 'Failed to update hosting password.')
    passwordMsgType.value = 'error'
  } finally {
    passwordBusy.value = false
  }
}

// Upgrade Flow
function openUpgrade() {
  if (!selectedService.value) return
  const higherPlans = props.plans.filter(
    (p) => Number(p.price_monthly) > Number(selectedService.value?.plan?.price_monthly || 0),
  )
  selectedUpgradePlanId.value = higherPlans[0]?.id || ''
  upgradeMsg.value = ''
  showUpgradeModal.value = true
}

async function submitUpgrade() {
  if (!selectedService.value?.sub || !selectedUpgradePlanId.value) return
  upgradeBusy.value = true
  upgradeMsg.value = ''
  try {
    const { data } = await customersApi.changePlan(
      selectedService.value.sub.id,
      selectedUpgradePlanId.value,
    )
    if (data.order_id) {
      void router.push(`/account/invoice/${data.order_id}`)
      return
    }
    showUpgradeModal.value = false
    actionMsg.value = data.message || 'Plan upgraded successfully!'
    actionMsgType.value = 'success'
    emit('refresh')
  } catch (err: unknown) {
    upgradeMsg.value = getApiErrorMessage(err, 'Upgrade request failed.')
  } finally {
    upgradeBusy.value = false
  }
}

// Renew Flow
async function triggerRenew() {
  if (!selectedService.value?.sub) return
  actionMsg.value = 'Generating renewal invoice…'
  actionMsgType.value = 'success'
  try {
    const { data } = await customersApi.renewSubscription(selectedService.value.sub.id)
    if (data.order_id) {
      void router.push(`/account/invoice/${data.order_id}`)
      return
    }
    actionMsg.value = data.message || 'Subscription renewed successfully.'
    actionMsgType.value = 'success'
    emit('refresh')
  } catch (err: unknown) {
    actionMsg.value = getApiErrorMessage(err, 'Renewal failed.')
    actionMsgType.value = 'error'
  }
}

// Cancel Flow
function openCancel() {
  showCancelModal.value = true
  cancelMsg.value = ''
}

async function submitCancel() {
  if (!selectedService.value?.sub) return
  cancelBusy.value = true
  cancelMsg.value = ''
  try {
    const fullReason = cancelDetails.value
      ? `${cancelReason.value}: ${cancelDetails.value}`
      : cancelReason.value
    const { data } = await customersApi.requestCancelSubscription(
      selectedService.value.sub.id,
      fullReason,
    )
    showCancelModal.value = false
    actionMsg.value = data.message || 'Cancellation request received. Auto-renew turned off.'
    actionMsgType.value = 'success'
    emit('refresh')
  } catch (err: unknown) {
    cancelMsg.value = getApiErrorMessage(err, 'Failed to submit cancellation request.')
  } finally {
    cancelBusy.value = false
  }
}
</script>

<template>
  <div class="services-container">
    <!-- Top Action Notice -->
    <div v-if="actionMsg" class="action-alert" :class="actionMsgType">
      <span>{{ actionMsg }}</span>
      <button type="button" class="alert-close" @click="actionMsg = ''">✕</button>
    </div>

    <!-- 1. LIST VIEW (Matching Image 2 & 3) -->
    <div v-if="!selectedService" class="services-list-view">
      <!-- Header -->
      <div class="services-head-bar">
        <div class="head-titles">
          <h1 class="page-title">My Products & Services</h1>
          <p class="page-subtitle">Manage active products, renewal dates, and billing cycles.</p>
        </div>

        <div class="head-actions">
          <RouterLink to="/plans" class="btn-top-order">
            <i class="fa-solid fa-cart-plus" /> + New Order
          </RouterLink>
          <button type="button" class="btn-top-ticket" @click="emit('openPanel', 'support')">
            <i class="fa-solid fa-comments" /> Open Ticket
          </button>
        </div>
      </div>

      <!-- Services Overview Card -->
      <div class="services-card">
        <div class="card-top-row">
          <div class="card-title-group">
            <h2 class="card-heading">Services Overview</h2>
            <span class="badge-count">{{ totalItems }} {{ totalItems === 1 ? 'item' : 'items' }}</span>
          </div>
        </div>

        <!-- Filter / Controls Row -->
        <div class="table-controls-row">
          <div class="entries-control">
            <select v-model="entriesPerPage" class="select-entries">
              <option :value="5">5</option>
              <option :value="10">10</option>
              <option :value="25">25</option>
              <option :value="50">50</option>
            </select>
            <span class="control-label">entries per page</span>
          </div>

          <div class="search-control">
            <label for="service-search" class="control-label">Search:</label>
            <input
              id="service-search"
              v-model="searchQuery"
              type="text"
              class="input-search"
              placeholder="Filter services…"
            />
          </div>
        </div>

        <!-- Table -->
        <div class="table-responsive">
          <table class="services-table">
            <thead>
              <tr>
                <th class="th-service">PRODUCT / SERVICE</th>
                <th class="th-pricing">PRICING</th>
                <th class="th-due">NEXT DUE DATE</th>
                <th class="th-status">STATUS</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in paginatedServices"
                :key="item.env.id"
                class="service-row"
                @click="selectService(item.env.id)"
              >
                <td class="td-service">
                  <div class="service-name-wrap">
                    <span class="service-title-link">
                      {{ item.planName }} for {{ item.domain }}
                    </span>
                    <span class="service-domain-sub">{{ item.domain }}</span>
                  </div>
                </td>
                <td class="td-pricing">
                  <div class="pricing-cell">
                    <span class="price-val">{{ item.currency }} {{ item.price.toFixed(2) }}</span>
                    <span class="price-cycle">{{ billingCycleText(item.billingTerm) }}</span>
                  </div>
                </td>
                <td class="td-due">
                  <span class="due-date-val">{{ formatDate(item.expiresAt) }}</span>
                </td>
                <td class="td-status">
                  <span
                    class="status-badge"
                    :class="{
                      active: item.status === 'active',
                      suspended: item.status === 'suspended',
                      canceled: item.status === 'cancelled' || item.status === 'canceled',
                      pending: item.status === 'pending' || item.status === 'provisioning',
                    }"
                  >
                    {{
                      item.status === 'active'
                        ? 'Active'
                        : item.status === 'suspended'
                          ? 'Suspended'
                          : item.status === 'cancelled' || item.status === 'canceled'
                            ? 'Canceled'
                            : 'Pending'
                    }}
                  </span>
                </td>
              </tr>

              <tr v-if="!paginatedServices.length">
                <td colspan="4" class="empty-table-cell">
                  <div class="empty-state-box">
                    <i class="fa-solid fa-server empty-icon" />
                    <p class="empty-msg">No hosting services found.</p>
                    <RouterLink to="/plans" class="btn-empty-order">Order a Hosting Package</RouterLink>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Pagination Footer -->
        <div v-if="totalPages > 1" class="pagination-footer">
          <span class="pagination-info">
            Showing {{ (currentPage - 1) * entriesPerPage + 1 }} to
            {{ Math.min(currentPage * entriesPerPage, totalItems) }} of {{ totalItems }} entries
          </span>
          <div class="pagination-btns">
            <button
              type="button"
              class="page-btn"
              :disabled="currentPage === 1"
              @click="currentPage--"
            >
              Previous
            </button>
            <button
              type="button"
              class="page-btn"
              :disabled="currentPage === totalPages"
              @click="currentPage++"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 2. SERVICE DETAILS VIEW (Matching Image 1 & 4) -->
    <div v-else class="service-details-view">
      <!-- Back & Actions Bar -->
      <div class="details-top-bar">
        <button type="button" class="btn-back" @click="backToList">
          <i class="fa-solid fa-arrow-left" /> Back to Products & Services
        </button>

        <div class="details-quick-actions">
          <button type="button" class="btn-action-outline" @click="openUpgrade">
            <i class="fa-solid fa-arrow-up-right-dots" /> Upgrade
          </button>
          <button type="button" class="btn-action-outline" @click="triggerRenew">
            <i class="fa-solid fa-arrows-rotate" /> Renew
          </button>
          <button type="button" class="btn-action-outline text-red" @click="openCancel">
            <i class="fa-solid fa-ban" /> Request Cancellation
          </button>
          <button type="button" class="btn-action-outline" @click="emit('openPanel', 'support')">
            <i class="fa-solid fa-comments" /> Open Ticket
          </button>
        </div>
      </div>

      <!-- Top Summary Card (Image 4) -->
      <div class="summary-hero-card">
        <div class="hero-head">
          <h1 class="hero-title">
            {{ selectedService.planName }} for {{ selectedService.domain }}
          </h1>
          <span
            class="status-badge"
            :class="{
              active: selectedService.status === 'active',
              suspended: selectedService.status === 'suspended',
              canceled: selectedService.status === 'cancelled' || selectedService.status === 'canceled',
              pending: selectedService.status === 'pending' || selectedService.status === 'provisioning',
            }"
          >
            {{
              selectedService.status === 'active'
                ? 'Active'
                : selectedService.status === 'suspended'
                  ? 'Suspended'
                  : selectedService.status === 'cancelled' || selectedService.status === 'canceled'
                    ? 'Canceled'
                    : 'Pending'
            }}
          </span>
        </div>

        <div class="summary-meta-grid">
          <div class="meta-row">
            <span class="meta-label">ID</span>
            <span class="meta-val font-mono">#{{ selectedService.idShort }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Payment amount</span>
            <span class="meta-val">{{ selectedService.currency }} {{ selectedService.price.toFixed(2) }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Billing cycle</span>
            <span class="meta-val">{{ billingCycleText(selectedService.billingTerm) }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Order created</span>
            <span class="meta-val">{{ formatDateTime(selectedService.createdAt) }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Activated at</span>
            <span class="meta-val">{{ formatDateTime(selectedService.createdAt) }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">
              Renewal date in {{ daysUntil(selectedService.expiresAt) }} day(s)
            </span>
            <span class="meta-val font-semibold">{{ formatDateTime(selectedService.expiresAt) }}</span>
          </div>
        </div>
      </div>

      <!-- Manage Hosting Account Section with Tabs (Image 1) -->
      <div class="manage-account-card">
        <div class="manage-card-head">
          <h2 class="manage-title">Manage Hosting Account</h2>
          <p class="manage-subtitle">Access hosting details, nameservers, and account credentials from one place.</p>
        </div>

        <!-- Tabs Navigation -->
        <div class="manage-tabs-bar">
          <button
            type="button"
            class="tab-btn"
            :class="{ active: activeTab === 'details' }"
            @click="activeTab = 'details'"
          >
            <i class="fa-solid fa-circle-info" /> Details
          </button>
          <button
            type="button"
            class="tab-btn"
            :class="{ active: activeTab === 'domains' }"
            @click="activeTab = 'domains'; loadCustomerDomains()"
          >
            <i class="fa-solid fa-globe" /> Domains
          </button>
          <button
            type="button"
            class="tab-btn"
            :class="{ active: activeTab === 'nameservers' }"
            @click="activeTab = 'nameservers'"
          >
            <i class="fa-solid fa-server" /> Nameservers
          </button>
          <button
            type="button"
            class="tab-btn"
            :class="{ active: activeTab === 'password' }"
            @click="activeTab = 'password'"
          >
            <i class="fa-solid fa-key" /> Password
          </button>
        </div>

        <!-- Tab 1: Details (Image 1) -->
        <div v-if="activeTab === 'details'" class="tab-content details-tab-pane">
          <div class="details-table-wrap">
            <div class="prop-row">
              <span class="prop-k">DOMAIN</span>
              <a
                :href="`https://${selectedService.domain}`"
                target="_blank"
                rel="noreferrer"
                class="prop-v link-domain"
              >
                {{ selectedService.domain }}
              </a>
            </div>

            <div class="prop-row">
              <span class="prop-k">SERVER IP</span>
              <span class="prop-v font-mono text-muted">Shared Hosting (Protected)</span>
            </div>

            <div class="prop-row">
              <span class="prop-k">HOSTNAME</span>
              <span class="prop-v font-mono">{{ selectedService.env.domain ? `fpanel.${selectedService.domain}` : 'node1.ifnotus.space' }}</span>
            </div>

            <div class="prop-row">
              <span class="prop-k">USERNAME</span>
              <span class="prop-v font-mono font-bold text-navy">{{ selectedService.username }}</span>
            </div>

            <div class="prop-row">
              <span class="prop-k">PASSWORD</span>
              <div class="prop-v password-reveal-row">
                <span class="font-mono">{{ showDetailsPass ? 'Set in Password tab' : '••••••••' }}</span>
                <button
                  type="button"
                  class="btn-eye-toggle"
                  title="Manage password"
                  @click="activeTab = 'password'"
                >
                  <i class="fa-solid fa-pen-to-square" />
                </button>
              </div>
            </div>

            <div class="prop-row">
              <span class="prop-k">HOSTING PLAN</span>
              <span class="prop-v font-semibold">{{ selectedService.planName }}</span>
            </div>

            <div class="prop-row">
              <span class="prop-k">BANDWIDTH</span>
              <span class="prop-v">
                {{ selectedService.plan?.bandwidth_tb ? `${Number(selectedService.plan.bandwidth_tb) * 1000000} MB / per month` : 'Unmetered' }}
              </span>
            </div>

            <div class="prop-row">
              <span class="prop-k">DISK QUOTA</span>
              <span class="prop-v font-mono">
                {{ selectedService.plan?.storage_gb ? `${selectedService.plan.storage_gb * 1024} MB` : `${selectedService.env.storage_limit_gb * 1024} MB` }}
              </span>
            </div>

            <div class="prop-row">
              <span class="prop-k">FPANEL URL</span>
              <a
                :href="`https://fpanel.${selectedService.domain}`"
                target="_blank"
                rel="noreferrer"
                class="prop-v link-cpanel"
              >
                fpanel.{{ selectedService.domain }}
              </a>
            </div>
          </div>

          <!-- Bottom Action: Login to fPanel Button (Image 1) -->
          <div class="details-bottom-bar">
            <button
              type="button"
              class="btn-login-cpanel"
              @click="launchFpanel(selectedService.domain, selectedService.env.id)"
            >
              Login to fPanel
            </button>
          </div>
        </div>

        <!-- Tab: Domains & Standalone Registration -->
        <div v-else-if="activeTab === 'domains'" class="tab-content domains-tab-pane">
          <!-- Propagation Notice Banner -->
          <div class="ns-notice">
            <i class="fa-solid fa-clock-rotate-left ns-info-ico" />
            <div>
              <p class="font-semibold text-slate-800 dark:text-slate-200">Domain Registration & Propagation</p>
              <p class="text-xs text-slate-600 dark:text-slate-400 mt-0.5">
                New domain purchases and DNS updates typically take <strong>24 to 48 hours</strong> to fully propagate worldwide across all Internet Service Providers. We will send you an SMS notification as soon as your domain is activated.
              </p>
            </div>
          </div>

          <!-- Buy / Register New Domain Box -->
          <div class="rounded-xl border border-surface-border bg-slate-50/60 p-4 dark:bg-slate-900/40 space-y-3">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
                Buy / Register Domain Only
              </span>
              <span class="text-xs text-brand-600 font-semibold dark:text-brand-400">
                .online ₵65/yr · .com ₵225/yr
              </span>
            </div>

            <form class="flex flex-col sm:flex-row gap-2" @submit.prevent="checkDomainAvailability">
              <input
                v-model="searchDomName"
                placeholder="type domain name (e.g. mycompany)"
                class="flex-1 rounded-lg border border-surface-border bg-white dark:bg-slate-800 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-500"
                :disabled="searchDomBusy || domainOrderBusy"
              />
              <select
                v-model="searchDomExt"
                class="rounded-lg border border-surface-border bg-white dark:bg-slate-800 px-3 py-2 text-sm font-semibold outline-none sm:w-32"
                :disabled="searchDomBusy || domainOrderBusy"
              >
                <option value=".online">.online</option>
                <option value=".com">.com</option>
                <option value=".org">.org</option>
                <option value=".net">.net</option>
                <option value=".xyz">.xyz</option>
                <option value=".store">.store</option>
                <option value=".tech">.tech</option>
                <option value=".site">.site</option>
              </select>
              <button
                type="submit"
                class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
                :disabled="searchDomBusy || domainOrderBusy || !searchDomName.trim()"
              >
                {{ searchDomBusy ? 'Checking…' : 'Check' }}
              </button>
            </form>

            <!-- Search Result Card -->
            <div
              v-if="searchDomResult"
              class="rounded-lg border p-3 text-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2"
              :class="searchDomResult.available ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-800/40 dark:bg-emerald-950/20' : 'border-amber-200 bg-amber-50 dark:border-amber-800/40 dark:bg-amber-950/20'"
            >
              <div>
                <p class="font-bold" :class="searchDomResult.available ? 'text-emerald-800 dark:text-emerald-300' : 'text-amber-800 dark:text-amber-300'">
                  {{ searchDomResult.domain }} {{ searchDomResult.available ? 'is available!' : 'is already registered.' }}
                </p>
                <p v-if="searchDomResult.available" class="text-xs text-emerald-700 dark:text-emerald-400">
                  Registration fee: GHS {{ searchDomResult.price_yearly }}/year · Fulfilled by IFNOTUS team
                </p>
              </div>

              <button
                v-if="searchDomResult.available"
                type="button"
                class="rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs px-3.5 py-2 disabled:opacity-50"
                :disabled="domainOrderBusy"
                @click="orderStandaloneDomain"
              >
                {{ domainOrderBusy ? 'Placing Order…' : 'Order Domain Only' }}
              </button>
            </div>

            <p
              v-if="domainOrderMsg"
              class="text-xs rounded p-2"
              :class="domainOrderSuccess ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-red-100 text-red-800 dark:bg-red-950/40 dark:text-red-300'"
            >
              {{ domainOrderMsg }}
            </p>
          </div>

          <!-- Existing Registered Domains Table -->
          <div class="mt-4 space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold uppercase tracking-wider text-slate-500">Your Registered Domains</span>
              <button
                type="button"
                class="text-xs text-brand-600 hover:underline font-semibold"
                :disabled="domainsLoading"
                @click="loadCustomerDomains"
              >
                {{ domainsLoading ? 'Refreshing…' : '↻ Refresh' }}
              </button>
            </div>

            <div v-if="domainsLoading" class="p-4 text-center text-xs text-slate-500">
              Loading domains…
            </div>
            <div v-else-if="customerDomains.length === 0" class="rounded-lg border border-surface-border p-4 text-center text-xs text-slate-500">
              No registered domains found on your account. You can search and buy one above.
            </div>
            <div v-else class="space-y-2">
              <div
                v-for="dom in customerDomains"
                :key="dom.id"
                class="rounded-lg border border-surface-border bg-white dark:bg-slate-800/80 p-3 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2"
              >
                <div>
                  <div class="flex items-center gap-2">
                    <span class="font-bold text-sm text-slate-900 dark:text-white">{{ dom.domain_name }}</span>
                    <span
                      class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide"
                      :class="dom.is_active ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300' : 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300'"
                    >
                      {{ dom.is_active ? 'Active' : 'Pending Activation (24-48h propagation)' }}
                    </span>
                  </div>
                  <p class="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                    <span v-if="dom.expiry_date">Renews: {{ formatDate(dom.expiry_date) }} · </span>
                    <span>Status: {{ dom.status }}</span>
                    <span v-if="dom.environment_domain"> · Attached to {{ dom.environment_domain }}</span>
                  </p>
                </div>

                <a
                  v-if="dom.is_active"
                  :href="`https://${dom.domain_name}`"
                  target="_blank"
                  rel="noreferrer"
                  class="text-xs font-semibold text-brand-600 hover:underline inline-flex items-center gap-1"
                >
                  Visit Site <i class="fa-solid fa-arrow-up-right-from-square text-[10px]" />
                </a>
                <span v-else class="text-[11px] text-amber-700 dark:text-amber-400 italic">
                  Propagating (24–48 hrs)
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Tab 2: Nameservers -->
        <div v-else-if="activeTab === 'nameservers'" class="tab-content nameservers-tab-pane">
          <div class="ns-notice">
            <i class="fa-solid fa-circle-info ns-info-ico" />
            <p>
              Point your domain name to the IFNOTUS nameservers below at your domain registrar (e.g. Namecheap, GoDaddy).
              DNS propagation usually takes between 15 minutes and 24 hours.
            </p>
          </div>

          <div class="details-table-wrap">
            <div class="prop-row">
              <span class="prop-k">NAMESERVER 1</span>
              <div class="prop-v ns-val-row">
                <span class="font-mono font-bold">ns1.ifnotus.space</span>
                <span class="ns-ip-tag">(Primary)</span>
              </div>
            </div>

            <div class="prop-row">
              <span class="prop-k">NAMESERVER 2</span>
              <div class="prop-v ns-val-row">
                <span class="font-mono font-bold">ns2.ifnotus.space</span>
                <span class="ns-ip-tag">(Primary)</span>
              </div>
            </div>

            <div class="prop-row">
              <span class="prop-k">NAMESERVER 3</span>
              <div class="prop-v ns-val-row">
                <span class="font-mono">ns3.ifnotus.space</span>
                <span class="ns-ip-tag">(Optional secondary)</span>
              </div>
            </div>

            <div class="prop-row">
              <span class="prop-k">NAMESERVER 4</span>
              <div class="prop-v ns-val-row">
                <span class="font-mono">ns4.ifnotus.space</span>
                <span class="ns-ip-tag">(Optional secondary)</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Tab 3: Password (Hosting fPanel Credentials) -->
        <div v-else class="tab-content password-tab-pane">
          <div v-if="passwordMsg" class="pass-alert" :class="passwordMsgType">
            {{ passwordMsg }}
          </div>

          <form class="password-form" @submit.prevent="saveHostingPassword">
            <div class="form-field">
              <label class="form-label">Default System Username</label>
              <div class="username-static-box">
                <span class="font-mono font-bold text-navy">{{ selectedService.username }}</span>
                <span class="sub-badge">Assigned by System</span>
              </div>
            </div>

            <div class="form-field">
              <div class="label-with-action">
                <label class="form-label">New Hosting Password</label>
                <button type="button" class="btn-gen-pass" @click="generatePassword">
                  <i class="fa-solid fa-wand-magic-sparkles" /> Generate Strong Password
                </button>
              </div>

              <div class="input-password-wrap">
                <input
                  v-model="newPassword"
                  :type="showNewPassword ? 'text' : 'password'"
                  class="input-pass"
                  placeholder="Enter at least 8 characters…"
                  required
                />
                <button
                  type="button"
                  class="btn-toggle-eye"
                  @click="showNewPassword = !showNewPassword"
                >
                  <IconEyeOff v-if="showNewPassword" :size="16" />
                  <IconEye v-else :size="16" />
                </button>
              </div>
            </div>

            <div class="form-field">
              <label class="form-label">Confirm New Password</label>
              <input
                v-model="confirmPassword"
                :type="showNewPassword ? 'text' : 'password'"
                class="input-pass"
                placeholder="Re-enter password…"
                required
              />
            </div>

            <div class="form-actions-row">
              <button
                type="submit"
                class="btn-save-password"
                :disabled="passwordBusy"
              >
                <i v-if="passwordBusy" class="fa-solid fa-circle-notch fa-spin" />
                <span v-else>Save Hosting Password</span>
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- UPGRADE MODAL -->
    <div v-if="showUpgradeModal" class="modal-overlay" @click.self="showUpgradeModal = false">
      <div class="modal-card">
        <div class="modal-head">
          <h3 class="modal-title">Upgrade Hosting Plan</h3>
          <button type="button" class="btn-close-modal" @click="showUpgradeModal = false">✕</button>
        </div>

        <div class="modal-body">
          <p class="modal-desc">
            Select a higher tier hosting plan for <strong>{{ selectedService?.domain }}</strong>.
          </p>

          <div v-if="upgradeMsg" class="modal-alert error">
            {{ upgradeMsg }}
          </div>

          <div class="plans-selection-list">
            <label
              v-for="p in plans"
              :key="p.id"
              class="plan-option-card"
              :class="{ selected: selectedUpgradePlanId === p.id }"
            >
              <input
                v-model="selectedUpgradePlanId"
                type="radio"
                :value="p.id"
                class="radio-input"
              />
              <div class="plan-option-info">
                <span class="plan-option-name">{{ p.name }}</span>
                <span class="plan-option-specs">
                  {{ p.storage_gb }}GB Storage · {{ p.ram_gb }}GB RAM · {{ p.cpu_cores }} Cores
                </span>
              </div>
              <div class="plan-option-price">
                <span class="price-num">GH₵ {{ Number(p.price_monthly).toFixed(2) }}</span>
                <span class="price-per">/ mo</span>
              </div>
            </label>
          </div>
        </div>

        <div class="modal-footer">
          <button type="button" class="btn-modal-cancel" @click="showUpgradeModal = false">Cancel</button>
          <button
            type="button"
            class="btn-modal-confirm"
            :disabled="upgradeBusy || !selectedUpgradePlanId"
            @click="submitUpgrade"
          >
            <i v-if="upgradeBusy" class="fa-solid fa-circle-notch fa-spin" />
            <span v-else>Proceed to Upgrade</span>
          </button>
        </div>
      </div>
    </div>

    <!-- CANCELLATION MODAL -->
    <div v-if="showCancelModal" class="modal-overlay" @click.self="showCancelModal = false">
      <div class="modal-card">
        <div class="modal-head">
          <h3 class="modal-title text-red">Request Cancellation</h3>
          <button type="button" class="btn-close-modal" @click="showCancelModal = false">✕</button>
        </div>

        <div class="modal-body">
          <p class="modal-desc">
            We are sorry to see you go. Cancellation will disable auto-renewal, and your hosting service
            for <strong>{{ selectedService?.domain }}</strong> will remain accessible until the end of the current billing period.
          </p>

          <div v-if="cancelMsg" class="modal-alert error">
            {{ cancelMsg }}
          </div>

          <div class="form-field">
            <label class="form-label">Reason for cancellation</label>
            <select v-model="cancelReason" class="input-pass">
              <option value="No longer needed">No longer needed</option>
              <option value="Migrating to another provider">Migrating to another provider</option>
              <option value="Technical difficulties">Technical difficulties</option>
              <option value="Pricing / Billing concern">Pricing / Billing concern</option>
              <option value="Other reason">Other reason</option>
            </select>
          </div>

          <div class="form-field">
            <label class="form-label">Additional notes (optional)</label>
            <textarea
              v-model="cancelDetails"
              class="input-pass textarea-reason"
              rows="3"
              placeholder="Tell us what we could improve…"
            />
          </div>
        </div>

        <div class="modal-footer">
          <button type="button" class="btn-modal-cancel" @click="showCancelModal = false">Keep Hosting</button>
          <button
            type="button"
            class="btn-modal-confirm btn-danger"
            :disabled="cancelBusy"
            @click="submitCancel"
          >
            <i v-if="cancelBusy" class="fa-solid fa-circle-notch fa-spin" />
            <span v-else>Confirm Cancellation Request</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.services-container {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  width: 100%;
}

.action-alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 1.25rem;
  border-radius: 0.75rem;
  font-size: 0.9rem;
  font-weight: 500;
}
.action-alert.success {
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}
.action-alert.error {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}
.alert-close {
  background: none;
  border: none;
  font-size: 1rem;
  cursor: pointer;
  color: inherit;
  opacity: 0.7;
}

/* 1. Header Bar */
.services-head-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 1.25rem;
  padding: 0.25rem 0.25rem 0.5rem;
}
.page-title {
  font-size: 1.55rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.02em;
  margin: 0 0 0.35rem;
}
.page-subtitle {
  font-size: 0.88rem;
  color: #64748b;
  margin: 0;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.btn-top-order {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  background: #0284c7;
  color: #ffffff;
  font-weight: 600;
  font-size: 0.85rem;
  padding: 0.6rem 1.15rem;
  border-radius: 0.55rem;
  text-decoration: none;
  box-shadow: 0 1px 2px rgba(2, 132, 199, 0.15);
  transition: all 0.15s ease;
}
.btn-top-order:hover {
  background: #0369a1;
  transform: translateY(-1px);
}
.btn-top-ticket {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  background: #ffffff;
  color: #334155;
  font-weight: 600;
  font-size: 0.85rem;
  padding: 0.6rem 1.05rem;
  border-radius: 0.55rem;
  border: 1px solid #cbd5e1;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  transition: all 0.15s ease;
}
.btn-top-ticket:hover {
  background: #f8fafc;
  border-color: #94a3b8;
}

/* Services Card */
.services-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.03), 0 2px 4px -2px rgba(0, 0, 0, 0.03);
  overflow: hidden;
}
.card-top-row {
  padding: 1.25rem 1.75rem;
  border-bottom: 1px solid #f1f5f9;
}
.card-title-group {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.card-heading {
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.01em;
  margin: 0;
}
.badge-count {
  background: #0284c7;
  color: #ffffff;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 0.2rem 0.65rem;
  border-radius: 9999px;
}

/* Controls */
.table-controls-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 1rem;
  padding: 0.9rem 1.75rem;
  background: #f8fafc;
  border-bottom: 1px solid #f1f5f9;
}
.entries-control,
.search-control {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.control-label {
  font-size: 0.85rem;
  color: #475569;
  font-weight: 500;
}
.select-entries {
  padding: 0.35rem 0.6rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.4rem;
  background: #ffffff;
  font-size: 0.85rem;
  color: #1e293b;
}
.input-search {
  padding: 0.35rem 0.75rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.4rem;
  background: #ffffff;
  font-size: 0.85rem;
  color: #1e293b;
  min-width: 180px;
}

/* Table */
.table-responsive {
  width: 100%;
  overflow-x: auto;
}
.services-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}
.services-table th {
  padding: 0.95rem 1.75rem;
  background: #f1f5f9;
  font-size: 0.76rem;
  font-weight: 700;
  color: #334155;
  letter-spacing: 0.05em;
  border-bottom: 1px solid #e2e8f0;
}
.service-row {
  cursor: pointer;
  transition: all 0.15s ease;
  border-bottom: 1px solid #f1f5f9;
}
.service-row:hover {
  background: #f8fafc;
}
.services-table td {
  padding: 1.15rem 1.75rem;
  vertical-align: middle;
}
.service-name-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.service-title-link {
  font-size: 0.95rem;
  font-weight: 700;
  color: #0284c7;
}
.service-row:hover .service-title-link {
  text-decoration: underline;
}
.service-domain-sub {
  font-size: 0.8rem;
  color: #64748b;
}
.pricing-cell {
  display: flex;
  flex-direction: column;
}
.price-val {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e293b;
}
.price-cycle {
  font-size: 0.8rem;
  color: #64748b;
}
.due-date-val {
  font-size: 0.9rem;
  font-weight: 500;
  color: #334155;
}

/* Badges */
.status-badge {
  display: inline-block;
  padding: 0.25rem 0.75rem;
  border-radius: 9999px;
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: capitalize;
}
.status-badge.active {
  background: #16a34a;
  color: #ffffff;
}
.status-badge.suspended {
  background: #dc2626;
  color: #ffffff;
}
.status-badge.canceled {
  background: #0284c7;
  color: #ffffff;
}
.status-badge.pending {
  background: #eab308;
  color: #ffffff;
}

.empty-table-cell {
  padding: 3rem !important;
  text-align: center;
}
.empty-state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}
.empty-icon {
  font-size: 2.25rem;
  color: #cbd5e1;
}
.empty-msg {
  font-size: 1rem;
  color: #64748b;
  margin: 0;
}
.btn-empty-order {
  display: inline-block;
  background: #0284c7;
  color: #ffffff;
  font-weight: 600;
  font-size: 0.85rem;
  padding: 0.5rem 1.25rem;
  border-radius: 0.5rem;
  text-decoration: none;
}

/* Pagination */
.pagination-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 1.5rem;
  background: #ffffff;
  border-top: 1px solid #f1f5f9;
}
.pagination-info {
  font-size: 0.85rem;
  color: #64748b;
}
.pagination-btns {
  display: flex;
  gap: 0.5rem;
}
.page-btn {
  padding: 0.35rem 0.75rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  border-radius: 0.35rem;
  font-size: 0.85rem;
  cursor: pointer;
  color: #334155;
}
.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 2. DETAILS VIEW (Image 1 & 4) */
.service-details-view {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  width: 100%;
}

.details-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 1rem;
}
.btn-back {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: none;
  border: none;
  color: #0284c7;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0.3rem 0;
}
.btn-back:hover {
  text-decoration: underline;
}
.details-quick-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.btn-action-outline {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
  font-size: 0.82rem;
  font-weight: 600;
  padding: 0.45rem 0.85rem;
  border-radius: 0.45rem;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-action-outline:hover {
  background: #f8fafc;
  border-color: #94a3b8;
}
.btn-action-outline.text-red {
  color: #dc2626;
}
.btn-action-outline.text-red:hover {
  background: #fef2f2;
  border-color: #fca5a5;
}

/* Top Hero Card (Image 4) */
.summary-hero-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.03), 0 2px 4px -2px rgba(0, 0, 0, 0.03);
  overflow: hidden;
}
.hero-head {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  padding: 1.5rem 1.75rem;
  border-bottom: 1px solid #f1f5f9;
}
.hero-title {
  font-size: 1.35rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.01em;
  margin: 0;
}
.summary-meta-grid {
  display: flex;
  flex-direction: column;
}
.meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.75rem;
  border-bottom: 1px solid #f1f5f9;
}
.meta-row:nth-child(even) {
  background: #f8fafc;
}
.meta-row:last-child {
  border-bottom: none;
}
.meta-label {
  font-size: 0.88rem;
  font-weight: 700;
  color: #0f172a;
}
.meta-val {
  font-size: 0.88rem;
  color: #334155;
}

/* Manage Hosting Account Section (Image 1) */
.manage-account-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.03), 0 2px 4px -2px rgba(0, 0, 0, 0.03);
  overflow: hidden;
}
.manage-card-head {
  padding: 1.75rem 1.75rem 1rem;
}
.manage-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.01em;
  margin: 0 0 0.35rem;
}
.manage-subtitle {
  font-size: 0.88rem;
  color: #64748b;
  margin: 0;
}

/* Tabs Bar */
.manage-tabs-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0 1.75rem;
  margin-top: 0.75rem;
  border-bottom: 1px solid #e2e8f0;
}
.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.7rem 1.25rem;
  border-radius: 0.55rem 0.55rem 0 0;
  border: 1px solid transparent;
  border-bottom: none;
  background: transparent;
  font-size: 0.88rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s ease;
}
.tab-btn:hover {
  color: #0f172a;
}
.tab-btn.active {
  background: #0284c7;
  color: #ffffff;
  border-color: #0284c7;
}

/* Tab Content */
.tab-content {
  padding: 1.75rem;
}

/* Details Table Wrap (Image 1) */
.details-table-wrap {
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  overflow: hidden;
}
.prop-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.95rem 1.5rem;
  border-bottom: 1px solid #f1f5f9;
}
.prop-row:nth-child(even) {
  background: #f8fafc;
}
.prop-row:last-child {
  border-bottom: none;
}
.prop-k {
  font-size: 0.8rem;
  font-weight: 700;
  color: #475569;
  letter-spacing: 0.03em;
}
.prop-v {
  font-size: 0.9rem;
  color: #0f172a;
}
.link-domain,
.link-cpanel {
  color: #0284c7;
  text-decoration: none;
  font-weight: 600;
}
.link-domain:hover,
.link-cpanel:hover {
  text-decoration: underline;
}
.password-reveal-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.btn-eye-toggle {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.2rem;
}
.btn-eye-toggle:hover {
  color: #0284c7;
}
.text-navy {
  color: #0f172a;
}

.details-bottom-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 1.25rem;
}
.btn-login-cpanel {
  background: #0284c7;
  color: #ffffff;
  font-size: 0.9rem;
  font-weight: 700;
  padding: 0.65rem 1.4rem;
  border-radius: 0.5rem;
  border: none;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(2, 132, 199, 0.2);
  transition: background 0.15s ease;
}
.btn-login-cpanel:hover {
  background: #0369a1;
}

/* Nameservers Tab */
.ns-notice {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 0.6rem;
  padding: 0.85rem 1.1rem;
  margin-bottom: 1.25rem;
  font-size: 0.85rem;
  color: #0369a1;
}
.ns-info-ico {
  font-size: 1.1rem;
  margin-top: 0.15rem;
}
.ns-notice p {
  margin: 0;
}
.ns-val-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.ns-ip-tag {
  font-size: 0.8rem;
  color: #64748b;
}

/* Password Tab */
.password-notice {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
  font-size: 0.85rem;
  color: #334155;
}
.password-notice strong {
  display: block;
  font-size: 0.92rem;
  color: #0f172a;
  margin-bottom: 0.2rem;
}
.password-notice p {
  margin: 0;
  line-height: 1.4;
}
.pass-alert {
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.85rem;
  margin-bottom: 1.25rem;
  font-weight: 500;
}
.pass-alert.success {
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}
.pass-alert.error {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.password-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 540px;
}
.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.form-label {
  font-size: 0.85rem;
  font-weight: 700;
  color: #334155;
}
.label-with-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.btn-gen-pass {
  background: none;
  border: none;
  color: #0284c7;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
}
.btn-gen-pass:hover {
  text-decoration: underline;
}
.username-static-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  padding: 0.6rem 0.9rem;
}
.sub-badge {
  font-size: 0.72rem;
  color: #64748b;
  background: #ffffff;
  padding: 0.15rem 0.45rem;
  border-radius: 0.25rem;
  border: 1px solid #e2e8f0;
}
.input-password-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.input-pass {
  width: 100%;
  padding: 0.6rem 0.9rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  font-size: 0.9rem;
  color: #0f172a;
}
.input-pass:focus {
  outline: none;
  border-color: #0284c7;
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.15);
}
.btn-toggle-eye {
  position: absolute;
  right: 0.75rem;
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.2rem;
}
.btn-toggle-eye:hover {
  color: #0f172a;
}
.form-actions-row {
  margin-top: 0.5rem;
}
.btn-save-password {
  background: #0284c7;
  color: #ffffff;
  font-size: 0.88rem;
  font-weight: 700;
  padding: 0.65rem 1.25rem;
  border-radius: 0.5rem;
  border: none;
  cursor: pointer;
  transition: background 0.15s ease;
}
.btn-save-password:hover {
  background: #0369a1;
}
.btn-save-password:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modals */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
  padding: 1rem;
}
.modal-card {
  background: #ffffff;
  border-radius: 1rem;
  max-width: 520px;
  width: 100%;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid #f1f5f9;
}
.modal-title {
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}
.btn-close-modal {
  background: none;
  border: none;
  font-size: 1.1rem;
  color: #64748b;
  cursor: pointer;
}
.modal-body {
  padding: 1.5rem;
}
.modal-desc {
  font-size: 0.9rem;
  color: #475569;
  margin: 0 0 1.25rem;
}
.modal-alert {
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.85rem;
  margin-bottom: 1rem;
}
.modal-alert.error {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}
.plans-selection-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.plan-option-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.85rem 1rem;
  border: 1.5px solid #e2e8f0;
  border-radius: 0.65rem;
  cursor: pointer;
  transition: all 0.15s ease;
}
.plan-option-card:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
}
.plan-option-card.selected {
  border-color: #0284c7;
  background: #f0f9ff;
}
.radio-input {
  accent-color: #0284c7;
}
.plan-option-info {
  display: flex;
  flex-direction: column;
  flex: 1;
}
.plan-option-name {
  font-size: 0.92rem;
  font-weight: 700;
  color: #0f172a;
}
.plan-option-specs {
  font-size: 0.78rem;
  color: #64748b;
}
.plan-option-price {
  text-align: right;
}
.price-num {
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}
.price-per {
  font-size: 0.78rem;
  color: #64748b;
}
.textarea-reason {
  resize: vertical;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  background: #f8fafc;
  border-top: 1px solid #f1f5f9;
}
.btn-modal-cancel {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #475569;
  font-size: 0.85rem;
  font-weight: 600;
  padding: 0.55rem 1rem;
  border-radius: 0.45rem;
  cursor: pointer;
}
.btn-modal-confirm {
  background: #0284c7;
  color: #ffffff;
  border: none;
  font-size: 0.85rem;
  font-weight: 700;
  padding: 0.55rem 1.15rem;
  border-radius: 0.45rem;
  cursor: pointer;
}
.btn-modal-confirm:hover {
  background: #0369a1;
}
.btn-modal-confirm.btn-danger {
  background: #dc2626;
}
.btn-modal-confirm.btn-danger:hover {
  background: #b91c1c;
}
.btn-modal-confirm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Dark Mode Adjustments */
:global(.dark) .services-card,
:global(.dark) .summary-hero-card,
:global(.dark) .manage-account-card,
:global(.dark) .modal-card {
  background: #0f172a;
  border-color: #1e293b;
}
:global(.dark) .page-title,
:global(.dark) .card-heading,
:global(.dark) .hero-title,
:global(.dark) .manage-title,
:global(.dark) .meta-label,
:global(.dark) .prop-v,
:global(.dark) .text-navy {
  color: #f1f5f9;
}
:global(.dark) .table-controls-row,
:global(.dark) .meta-row:nth-child(even),
:global(.dark) .prop-row:nth-child(even),
:global(.dark) .modal-footer,
:global(.dark) .password-notice {
  background: #1e293b;
}
:global(.dark) .services-table th {
  background: #1e293b;
  color: #f8fafc;
  border-color: #334155;
}
:global(.dark) .service-row:hover {
  background: #1e293b;
}
:global(.dark) .details-table-wrap,
:global(.dark) .plan-option-card,
:global(.dark) .username-static-box,
:global(.dark) .input-pass {
  border-color: #334155;
  background: #0f172a;
  color: #f1f5f9;
}
:global(.dark) .btn-top-ticket,
:global(.dark) .btn-action-outline,
:global(.dark) .btn-modal-cancel {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}
</style>
