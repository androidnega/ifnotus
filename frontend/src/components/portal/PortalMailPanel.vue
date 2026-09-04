<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { customersApi } from '@/api'
import { tenantMailUrl, isCustomerCpanelHost, tenantCpanelUrl } from '@/lib/platformHosts'
import { IconEye, IconEyeOff } from '@/components/icons'

export interface MailboxRow {
  id: string
  email: string
  local_part?: string
  quota_mb?: number | null
  used_mb?: number | null
  suspended?: boolean
  is_system?: boolean
}

export interface AliasRow {
  id: string
  source_email: string
  destination: string
  enabled: boolean
}

const props = defineProps<{
  environmentId: string
  domain?: string | null
  mailboxLimit?: number | null
  storageLimitMb?: number | null
}>()

// Navigation state
const viewMode = ref<'list' | 'create'>('list')
const activeFilter = ref<'all' | 'restricted' | 'system' | 'exceeded'>('all')
const searchQuery = ref('')
const selectedMailboxIds = ref<Set<string>>(new Set())

// Data state
const loading = ref(true)
const error = ref('')
const msg = ref<{ type: 'ok' | 'err'; text: string } | null>(null)
const mailboxes = ref<MailboxRow[]>([])
const aliases = ref<AliasRow[]>([])
const attachedDomains = ref<string[]>([])
const primaryDomain = ref(props.domain || '')
const systemUsername = ref('user')
const webmailUrl = ref('https://mail.ifnotus.space/')
const clients = ref<Record<string, unknown> | null>(null)
const busyId = ref('')

// Create Form State
const selectedDomain = ref('')
const newUsername = ref('')
const newPassword = ref('')
const showPassword = ref(false)
const showHelp = ref(true)
const showOptionalSettings = ref(false)
const storageQuotaType = ref<'250' | 'custom' | 'unlimited'>('250')
const customStorageMb = ref(500)
const sendWelcomeEmail = ref(true)
const creating = ref(false)

// Manage / Modal State
const manageTarget = ref<MailboxRow | null>(null)
const manageQuotaType = ref<'250' | 'custom' | 'unlimited'>('250')
const manageCustomMb = ref(250)
const managePassword = ref('')
const showManagePassword = ref(false)
const manageBusy = ref(false)

// Connect Devices Modal State
const connectTarget = ref<MailboxRow | null>(null)

// Stats calculation
const totalUsedCount = computed(() => mailboxes.value.length)

const maxAvailableCount = computed(() => {
  if (props.mailboxLimit != null) return props.mailboxLimit
  return 32
})

const availableCount = computed(() => {
  const max = maxAvailableCount.value
  return Math.max(0, max - totalUsedCount.value)
})

const passwordStrength = computed(() => {
  const p = newPassword.value
  if (!p) return 0
  let s = 0
  if (p.length >= 8) s += 25
  if (p.length >= 12) s += 25
  if (/[A-Z]/.test(p) && /[a-z]/.test(p)) s += 25
  if (/\d/.test(p) && /[^A-Za-z0-9]/.test(p)) s += 25
  return s
})

const passwordStrengthLabel = computed(() => {
  const s = passwordStrength.value
  if (s <= 25) return 'Very Weak'
  if (s <= 50) return 'Weak'
  if (s <= 75) return 'Good'
  return 'Strong'
})

const allMailboxItems = computed<MailboxRow[]>(() => {
  // Only real IMAP mailboxes — do not invent a "system" address (unix_username@domain)
  // that cannot authenticate in Dovecot/Roundcube.
  return [...mailboxes.value]
})

const filteredMailboxes = computed(() => {
  let list = allMailboxItems.value
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter((m) => m.email.toLowerCase().includes(q))
  }
  if (activeFilter.value === 'restricted') {
    list = list.filter((m) => m.suspended)
  } else if (activeFilter.value === 'system') {
    list = list.filter((m) => m.is_system)
  } else if (activeFilter.value === 'exceeded') {
    list = list.filter((m) => m.quota_mb && (m.used_mb || 0) >= m.quota_mb)
  }
  return list
})

const isAllSelected = computed(() => {
  const nonSystem = filteredMailboxes.value.filter((m) => !m.is_system)
  return nonSystem.length > 0 && nonSystem.every((m) => selectedMailboxIds.value.has(m.id))
})

function toggleSelectAll() {
  if (isAllSelected.value) {
    selectedMailboxIds.value.clear()
  } else {
    for (const m of filteredMailboxes.value) {
      if (!m.is_system) selectedMailboxIds.value.add(m.id)
    }
  }
}

function toggleSelect(id: string) {
  if (selectedMailboxIds.value.has(id)) {
    selectedMailboxIds.value.delete(id)
  } else {
    selectedMailboxIds.value.add(id)
  }
}

function generatePassword() {
  const chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*+='
  let p = ''
  for (let i = 0; i < 16; i++) {
    p += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  newPassword.value = p
  showPassword.value = true
}

function generateManagePassword() {
  const chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*+='
  let p = ''
  for (let i = 0; i < 16; i++) {
    p += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  managePassword.value = p
  showManagePassword.value = true
}

async function load() {
  if (!props.environmentId) return
  loading.value = true
  error.value = ''
  try {
    const [mailRes, domRes] = await Promise.allSettled([
      customersApi.getEnvMail(props.environmentId),
      customersApi.listEnvDomainItems(props.environmentId),
    ])

    if (mailRes.status === 'fulfilled' && mailRes.value.data) {
      const data = mailRes.value.data
    mailboxes.value = data.mailboxes || []
    aliases.value = data.aliases || []
      // Prefer the Domain row used by Dovecot (mailboxes), not a mismatched env.domain.
      primaryDomain.value = data.domain?.name || props.domain || ''
      const fallbackWebmail = primaryDomain.value ? tenantMailUrl(primaryDomain.value) : 'https://mail.ifnotus.space/'
      webmailUrl.value = data.webmail_url || data.clients?.webmail_url || fallbackWebmail || 'https://mail.ifnotus.space/'
    clients.value = data.clients || null
    }

    if (domRes.status === 'fulfilled' && domRes.value.data) {
      const domData = domRes.value.data
      // Do not overwrite mail domain with a different env primary — that breaks login addresses.
      if (!primaryDomain.value && domData.primary_domain) primaryDomain.value = domData.primary_domain
      if (domData.unix_username) systemUsername.value = domData.unix_username
      const domList = (domData.items || []).map((i) => i.domain_name.trim().toLowerCase()).filter(Boolean)
      attachedDomains.value = Array.from(new Set([primaryDomain.value, ...domList])).filter(Boolean)
    } else if (primaryDomain.value) {
      attachedDomains.value = [primaryDomain.value]
    }

    if (!selectedDomain.value && attachedDomains.value.length > 0) {
      selectedDomain.value = attachedDomains.value[0]
    }
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = x.response?.data?.error?.message ?? 'Could not load email configuration.'
  } finally {
    loading.value = false
  }
}

async function createAccount() {
  if (!newUsername.value.trim()) {
    msg.value = { type: 'err', text: 'Username is required.' }
    return
  }
  // Always require a real mailbox password (Roundcube/IMAP). "Send link" without a
  // password previously left users unable to log in.
  if (newPassword.value.length < 8) {
    msg.value = { type: 'err', text: 'Password must be at least 8 characters long.' }
    return
  }

  let quota: number | null = 250
  if (storageQuotaType.value === 'unlimited') quota = null
  else if (storageQuotaType.value === 'custom') quota = Number(customStorageMb.value) || 250

  const dom = selectedDomain.value || primaryDomain.value
  const local = newUsername.value.trim().toLowerCase()
  creating.value = true
  msg.value = null

  try {
    await customersApi.createEnvMailbox(props.environmentId, {
      local_part: local,
      password: newPassword.value,
    })
    msg.value = {
      type: 'ok',
      text: `Success: Email account "${local}@${dom}" created successfully!`,
    }
    newUsername.value = ''
    newPassword.value = ''
    viewMode.value = 'list'
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Could not create email account.' }
  } finally {
    creating.value = false
  }
}

async function deleteSelected() {
  const ids = Array.from(selectedMailboxIds.value)
  if (!ids.length) return
  if (!confirm(`Are you sure you want to delete ${ids.length} selected email account(s)? This will delete all stored mail.`)) {
    return
  }

  msg.value = null
  try {
    for (const id of ids) {
      await customersApi.deleteEnvMailbox(props.environmentId, id).catch(() => null)
    }
    selectedMailboxIds.value.clear()
    msg.value = { type: 'ok', text: 'Selected mailbox(es) deleted successfully.' }
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Delete failed.' }
  }
}

function openManage(m: MailboxRow) {
  if (m.is_system) return
  manageTarget.value = m
  managePassword.value = ''
  showManagePassword.value = false
  if (m.quota_mb == null) {
    manageQuotaType.value = 'unlimited'
  } else if (m.quota_mb === 250) {
    manageQuotaType.value = '250'
  } else {
    manageQuotaType.value = 'custom'
    manageCustomMb.value = m.quota_mb
  }
}

async function saveManage() {
  if (!manageTarget.value) return
  manageBusy.value = true
  msg.value = null
  try {
    let quota: number | null = 250
    if (manageQuotaType.value === 'unlimited') quota = null
    else if (manageQuotaType.value === 'custom') quota = Number(manageCustomMb.value) || 250

    await customersApi.updateEnvMailbox(props.environmentId, manageTarget.value.id, {
      quota_mb: quota,
      ...(managePassword.value ? { password: managePassword.value } : {}),
    })

    msg.value = { type: 'ok', text: `Updated settings for ${manageTarget.value.email}.` }
    manageTarget.value = null
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Update failed.' }
  } finally {
    manageBusy.value = false
  }
}

function openConnect(m: MailboxRow) {
  connectTarget.value = m
}

function openWebmail(m: MailboxRow) {
  const url = webmailUrl.value || 'https://mail.ifnotus.space/'
  window.open(url, '_blank')
}

function navigateToDomains() {
  if (isCustomerCpanelHost()) {
    window.location.href = '/domains'
  } else {
    window.location.href = `/hosting/${encodeURIComponent(props.environmentId)}/domains`
  }
}

watch(() => props.environmentId, (id) => {
  if (id) void load()
})

onMounted(load)
</script>

<template>
  <div class="cpanel-email-pane">
    <!-- Breadcrumb Header -->
    <div class="cp-mail-header">
      <div class="cp-mail-title-block">
        <h1 class="cp-mail-main-title">Email Accounts</h1>
        <div class="cp-mail-crumbs">
          <span
            class="crumb-link"
            :class="{ active: viewMode === 'list' }"
            @click="viewMode = 'list'"
          >
            List Email Accounts
          </span>
          <template v-if="viewMode === 'create'">
            <span class="crumb-sep">/</span>
            <span class="crumb-link active">Create an Email Account</span>
          </template>
        </div>
        <p class="cp-mail-desc">
          This feature lets you create and manage email accounts. Want to learn more?
          <a href="https://ifnotus.space" target="_blank" rel="noopener" class="cp-inline-link">
            Read our documentation <i class="fas fa-external-link-alt text-[10px]" />
          </a>.
        </p>
      </div>

      <!-- Top Right Available / Used Counter Card -->
      <div class="cp-stat-box">
        <div class="stat-cell">
          <span class="stat-num">{{ availableCount }}</span>
          <span class="stat-lbl">Available</span>
        </div>
        <div class="stat-divider" />
        <div class="stat-cell">
          <span class="stat-num">{{ totalUsedCount }}</span>
          <span class="stat-lbl">Used</span>
        </div>
      </div>
    </div>

    <!-- Alert / Notice Message -->
    <div
      v-if="msg"
      class="cp-alert-banner"
      :class="msg.type === 'ok' ? 'cp-alert-success' : 'cp-alert-error'"
    >
      <i :class="msg.type === 'ok' ? 'fas fa-check-circle' : 'fas fa-exclamation-triangle'" />
      <span>{{ msg.text }}</span>
      <button type="button" class="cp-alert-close" @click="msg = null">×</button>
    </div>

    <!-- ================================================================= -->
    <!-- 1. LIST EMAIL ACCOUNTS VIEW (Image 6) -->
    <!-- ================================================================= -->
    <section v-if="viewMode === 'list'" class="cp-list-section">
      <!-- Search and Filters Bar -->
      <div class="cp-search-filters-row">
        <div class="cp-search-wrap">
          <input
            v-model="searchQuery"
            type="text"
            class="cp-search-input"
            placeholder="Search"
          />
          <button type="button" class="cp-search-btn" aria-label="Search">
            <i class="fas fa-search" />
          </button>
        </div>

        <div class="cp-filter-pills-row">
          <span class="filter-label">Filter:</span>
          <button
            type="button"
            class="cp-filter-pill"
            :class="{ active: activeFilter === 'all' }"
            @click="activeFilter = 'all'"
          >
            All
          </button>
          <button
            type="button"
            class="cp-filter-pill"
            :class="{ active: activeFilter === 'restricted' }"
            @click="activeFilter = 'restricted'"
          >
            Restricted
          </button>
          <button
            type="button"
            class="cp-filter-pill"
            :class="{ active: activeFilter === 'system' }"
            @click="activeFilter = 'system'"
          >
            System Account
          </button>
          <button
            type="button"
            class="cp-filter-pill"
            :class="{ active: activeFilter === 'exceeded' }"
            @click="activeFilter = 'exceeded'"
          >
            Exceeded Storage
          </button>
        </div>

        <div class="cp-pagination-info">
          <button type="button" class="page-nav-btn" disabled>&lt;&lt;</button>
          <button type="button" class="page-nav-btn" disabled>&lt;</button>
          <span class="page-current">Page 1 of 1</span>
          <button type="button" class="page-nav-btn" disabled>&gt;</button>
          <button type="button" class="page-nav-btn" disabled>&gt;&gt;</button>
          <span class="page-count-text">1 - {{ filteredMailboxes.length }} of {{ filteredMailboxes.length }}</span>
        </div>
      </div>

      <!-- Action Toolbar -->
      <div class="cp-action-toolbar">
        <div class="toolbar-left">
          <label class="cp-checkbox-label">
            <input
              type="checkbox"
              :checked="isAllSelected"
              @change="toggleSelectAll"
            />
          </label>
          <button
            type="button"
            class="cp-btn cp-btn-default cp-btn-sm"
            :disabled="!selectedMailboxIds.size"
            @click="deleteSelected"
          >
            <i class="fas fa-trash-alt mr-1 text-red-500" /> Delete
          </button>
        </div>

        <div class="toolbar-right">
          <button
            type="button"
            class="cp-btn cp-btn-primary"
            @click="viewMode = 'create'"
          >
            <i class="fas fa-plus mr-1" /> Create
          </button>
          <button type="button" class="cp-btn-icon-cog" title="Settings">
            <i class="fas fa-cog" />
          </button>
        </div>
      </div>

      <!-- Email Accounts Table -->
      <div class="cp-table-container">
        <table class="cp-email-table">
          <thead>
            <tr>
              <th class="th-check">
                <input
                  type="checkbox"
                  :checked="isAllSelected"
                  @change="toggleSelectAll"
                />
              </th>
              <th class="th-expand" />
              <th class="th-account">
                <div class="th-header-sort">
                  <span>Account @ Domain</span>
                  <i class="fas fa-caret-up text-sky-600" />
                </div>
              </th>
              <th class="th-restrictions">Restrictions</th>
              <th class="th-storage">Storage: Used / Allocated / %</th>
              <th class="th-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading" class="tr-empty">
              <td colspan="6" class="td-loading">
                <i class="fas fa-spinner fa-spin" /> Loading email accounts…
              </td>
            </tr>
            <tr v-else-if="!filteredMailboxes.length" class="tr-empty">
              <td colspan="6" class="td-no-records">
                No email accounts found. Click <strong>"+ Create"</strong> above to add an email address.
              </td>
            </tr>
            <tr
              v-for="box in filteredMailboxes"
              :key="box.id"
              class="cp-mail-row"
              :class="{ selected: selectedMailboxIds.has(box.id) }"
            >
              <td class="td-check">
                <input
                  v-if="!box.is_system"
                  type="checkbox"
                  :checked="selectedMailboxIds.has(box.id)"
                  @change="toggleSelect(box.id)"
                />
              </td>
              <td class="td-expand">
                <i class="fas fa-chevron-right text-slate-400 text-xs" />
              </td>
              <td class="td-account">
                <div class="account-cell">
                  <span class="account-email font-mono">{{ box.email }}</span>
                  <span v-if="box.is_system" class="badge-system">System</span>
                </div>
              </td>
              <td class="td-restrictions">
                <span v-if="!box.suspended" class="status-unrestricted">
                  <i class="fas fa-check text-emerald-600 mr-1" /> Unrestricted
                </span>
                <span v-else class="status-restricted">
                  <i class="fas fa-ban text-red-600 mr-1" /> Restricted
                </span>
              </td>
              <td class="td-storage">
                <div class="storage-cell">
                  <div class="storage-text">
                    <span>{{ box.used_mb ? (box.used_mb > 1 ? box.used_mb.toFixed(2) + ' MB' : (box.used_mb * 1024).toFixed(0) + ' KB') : '0 KB' }}</span>
                    <span>/</span>
                    <span>{{ box.quota_mb ? box.quota_mb + ' MB' : '∞' }}</span>
                    <span v-if="box.quota_mb">/ {{ ((box.used_mb || 0) / box.quota_mb * 100).toFixed(2) }}%</span>
                  </div>
                  <div class="storage-progress-bar">
                    <div
                      class="progress-fill"
                      :style="{
                        width: box.quota_mb ? Math.min(100, Math.max(1, ((box.used_mb || 0) / box.quota_mb * 100))) + '%' : '1%',
                        backgroundColor: (box.used_mb || 0) > (box.quota_mb || 999999) * 0.9 ? '#ef4444' : '#10b981'
                      }"
                    />
                  </div>
                </div>
              </td>
              <td class="td-actions">
                <div class="actions-group">
                  <button
                    type="button"
                    class="cp-btn-action"
                    @click="openWebmail(box)"
                  >
                    <i class="fas fa-external-link-alt" /> Check Email
                  </button>
                  <button
                    v-if="!box.is_system"
                    type="button"
                    class="cp-btn-action"
                    @click="openManage(box)"
                  >
                    <i class="fas fa-wrench" /> Manage
                  </button>
                  <button
                    type="button"
                    class="cp-btn-action"
                    @click="openConnect(box)"
                  >
                    Connect Devices
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- ================================================================= -->
    <!-- 2. CREATE AN EMAIL ACCOUNT VIEW (Image 7) -->
    <!-- ================================================================= -->
    <section v-else-if="viewMode === 'create'" class="cp-create-section">
      <div class="cp-create-grid">
        <!-- Left Form Column -->
        <div class="cp-create-card">
          <div class="card-top-bar">
            <h2 class="card-heading">CREATE AN EMAIL ACCOUNT</h2>
            <button
              type="button"
              class="btn-help-toggle"
              @click="showHelp = !showHelp"
            >
              {{ showHelp ? 'Hide Help' : 'Show Help' }} <i class="fas fa-question-circle ml-1" />
            </button>
          </div>

          <form class="cp-create-form" @submit.prevent="createAccount">
            <!-- Domain Selection -->
            <div class="form-group">
              <label class="form-label">
                Domain <i class="fas fa-question-circle text-sky-600 cursor-pointer ml-1" />
              </label>
              <select v-model="selectedDomain" class="cp-select">
                <option v-for="d in attachedDomains" :key="d" :value="d">
                  {{ d }}
                </option>
              </select>
              <p class="form-sub-hint">
                Missing a domain? Check the <em>Missing a domain?</em> section to find out how you can create one.
              </p>
              </div>

            <!-- Username Input -->
            <div class="form-group">
              <label class="form-label">
                Username <i class="fas fa-question-circle text-sky-600 cursor-pointer ml-1" />
            </label>
              <div class="cp-addon-input-wrap">
                <input
                  v-model="newUsername"
                  type="text"
                  class="cp-addon-input"
                  placeholder="Enter your email address's username here."
                  required
                />
                <span class="cp-addon-suffix">@{{ selectedDomain || primaryDomain }}</span>
              </div>
              <button
                type="button"
                class="cp-link-btn text-xs text-sky-600 mt-1"
                @click="navigateToDomains"
              >
                Missing a domain?
              </button>
            </div>

            <!-- Password Options -->
            <div class="form-group">
              <label class="form-label">Password</label>
              <div class="mt-2">
                <div class="password-input-group">
                  <input
                    v-model="newPassword"
                  :type="showPassword ? 'text' : 'password'"
                    class="cp-input"
                    placeholder="Enter Password"
                  minlength="8"
                  required
                />
                <button
                  type="button"
                    class="btn-eye-toggle"
                  :title="showPassword ? 'Hide password' : 'Show password'"
                  @click="showPassword = !showPassword"
                >
                    <IconEyeOff v-if="showPassword" :size="16" />
                    <IconEye v-else :size="16" />
                  </button>
                  <button
                    type="button"
                    class="btn-generate-password"
                    @click="generatePassword"
                  >
                    Generate <i class="fas fa-caret-down ml-1" />
                </button>
              </div>

                <!-- Strength Meter -->
                <div class="strength-meter-wrap mt-2">
                  <div class="strength-bar-track">
                    <div
                      class="strength-bar-fill"
                      :style="{
                        width: passwordStrength + '%',
                        backgroundColor: passwordStrength > 70 ? '#10b981' : (passwordStrength > 40 ? '#f59e0b' : '#ef4444')
                      }"
                    />
                  </div>
                  <span class="strength-label text-xs font-semibold text-slate-500 mt-1">
                    Strength: {{ passwordStrengthLabel }} ({{ passwordStrength }} / 100)
                  </span>
                </div>
              </div>
            </div>

            <!-- Optional Settings Accordion -->
            <div class="optional-settings-box">
              <div class="opt-head" @click="showOptionalSettings = !showOptionalSettings">
                <span class="opt-title">Optional Settings</span>
                <button type="button" class="cp-btn cp-btn-default cp-btn-xs">
                  <i class="fas fa-edit mr-1" /> Edit Settings
                </button>
              </div>

              <div v-if="showOptionalSettings" class="opt-body">
                <div class="form-group mb-3">
                  <label class="form-label">Storage Space</label>
                  <div class="radio-options-stack">
                    <label class="radio-item">
                      <input
                        v-model="storageQuotaType"
                        type="radio"
                        value="250"
                      />
                      <span>250 MB (Default)</span>
            </label>
                    <label class="radio-item">
                      <input
                        v-model="storageQuotaType"
                        type="radio"
                        value="custom"
                      />
                      <span>Custom:</span>
                      <input
                        v-if="storageQuotaType === 'custom'"
                        v-model.number="customStorageMb"
                        type="number"
                        min="10"
                        class="cp-input cp-input-sm w-24 ml-2"
                      />
                      <span v-if="storageQuotaType === 'custom'" class="ml-1 text-xs text-slate-500">MB</span>
                    </label>
                    <label class="radio-item">
                      <input
                        v-model="storageQuotaType"
                        type="radio"
                        value="unlimited"
                      />
                      <span>Unlimited (∞)</span>
                    </label>
                  </div>
                </div>

                <div class="form-group">
                  <label class="checkbox-item">
                    <input v-model="sendWelcomeEmail" type="checkbox" />
                    <span class="text-xs">Send a welcome email with instructions to configure a mail client.</span>
                  </label>
                </div>
              </div>
            </div>

            <!-- Submit Button & Return -->
            <div class="form-actions-bar mt-5">
              <button
                type="submit"
                class="cp-btn cp-btn-primary"
                :disabled="creating"
              >
                <i v-if="creating" class="fas fa-spinner fa-spin mr-1" />
                <i v-else class="fas fa-plus mr-1" />
                + Create
            </button>
              <button
                type="button"
                class="cp-btn cp-btn-default ml-2"
                @click="viewMode = 'list'"
              >
                Return to Email Accounts
              </button>
            </div>
          </form>
          </div>

        <!-- Right Help / Navigation Sidebar (Image 7) -->
        <div class="cp-create-sidebar">
          <!-- Missing A Domain Card -->
          <div class="sidebar-info-card">
            <h3 class="side-card-title">MISSING A DOMAIN?</h3>
            <p class="side-card-text">
              Navigate to a full list of the account's domains to create a new addon domain or subdomain.
            </p>
                <button
                  type="button"
              class="side-card-btn"
              @click="navigateToDomains"
                >
              <i class="fas fa-wrench mr-1 text-sky-600" /> Manage Domains
                </button>
              </div>

          <!-- Need Help Card -->
          <div class="sidebar-info-card mt-4">
            <h3 class="side-card-title">NEED HELP?</h3>
            <a
              href="https://ifnotus.space"
              target="_blank"
              rel="noopener"
              class="side-card-link"
            >
              <i class="fas fa-external-link-alt mr-1 text-sky-600" /> About This Interface
            </a>
          </div>
        </div>
      </div>
    </section>

    <!-- ================================================================= -->
    <!-- 3. MANAGE MAILBOX MODAL -->
    <!-- ================================================================= -->
    <div v-if="manageTarget" class="cp-modal-overlay" @click.self="manageTarget = null">
      <div class="cp-modal-box">
        <div class="modal-head">
          <h3 class="modal-title">Manage Account: {{ manageTarget.email }}</h3>
          <button type="button" class="modal-close-btn" @click="manageTarget = null">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group mb-4">
            <label class="form-label">New Password (leave blank to keep current)</label>
            <div class="password-input-group">
              <input
                v-model="managePassword"
                :type="showManagePassword ? 'text' : 'password'"
                class="cp-input"
                placeholder="New Password"
                minlength="8"
              />
              <button
                type="button"
                class="btn-eye-toggle"
                @click="showManagePassword = !showManagePassword"
              >
                <IconEyeOff v-if="showManagePassword" :size="16" />
                <IconEye v-else :size="16" />
              </button>
              <button
                type="button"
                class="btn-generate-password"
                @click="generateManagePassword"
              >
                Generate
              </button>
            </div>
      </div>

          <div class="form-group mb-4">
            <label class="form-label">Storage Quota</label>
            <div class="radio-options-stack">
              <label class="radio-item">
                <input v-model="manageQuotaType" type="radio" value="250" />
                <span>250 MB</span>
          </label>
              <label class="radio-item">
                <input v-model="manageQuotaType" type="radio" value="custom" />
                <span>Custom:</span>
                <input
                  v-if="manageQuotaType === 'custom'"
                  v-model.number="manageCustomMb"
                  type="number"
                  min="10"
                  class="cp-input cp-input-sm w-24 ml-2"
                />
                <span v-if="manageQuotaType === 'custom'" class="ml-1 text-xs text-slate-500">MB</span>
          </label>
              <label class="radio-item">
                <input v-model="manageQuotaType" type="radio" value="unlimited" />
                <span>Unlimited (∞)</span>
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button
            type="button"
            class="cp-btn cp-btn-primary"
            :disabled="manageBusy"
            @click="saveManage"
          >
            <i v-if="manageBusy" class="fas fa-spinner fa-spin mr-1" />
            Save Changes
            </button>
          <button
            type="button"
            class="cp-btn cp-btn-default ml-2"
            @click="manageTarget = null"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>

    <!-- ================================================================= -->
    <!-- 4. CONNECT DEVICES MODAL -->
    <!-- ================================================================= -->
    <div v-if="connectTarget" class="cp-modal-overlay" @click.self="connectTarget = null">
      <div class="cp-modal-box cp-modal-wide">
        <div class="modal-head">
          <h3 class="modal-title">Mail Client Manual Settings: {{ connectTarget.email }}</h3>
          <button type="button" class="modal-close-btn" @click="connectTarget = null">×</button>
        </div>
        <div class="modal-body">
          <div class="cp-settings-grid">
            <div class="settings-box secure-box">
              <h4 class="box-title text-emerald-700 dark:text-emerald-400 font-bold">
                <i class="fas fa-lock mr-1" /> Secure SSL/TLS Settings (Recommended)
              </h4>
              <dl class="settings-dl">
                <dt>Username:</dt>
                <dd class="font-mono font-bold">{{ connectTarget.email }}</dd>
                <dt>Password:</dt>
                <dd>Use the email account's password.</dd>
                <dt>Incoming Server:</dt>
                <dd class="font-mono">mail.ifnotus.space (IMAP Port: 993, POP3 Port: 995)</dd>
                <dt>Outgoing Server:</dt>
                <dd class="font-mono">mail.ifnotus.space (SMTP Port: 465)</dd>
              </dl>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button
            type="button"
            class="cp-btn cp-btn-primary"
            @click="connectTarget = null"
          >
            Done
        </button>
            </div>
            </div>
          </div>
  </div>
</template>

<style scoped>
.cpanel-email-pane {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: #1e293b;
  width: 100%;
}

/* Header & Counter */
.cp-mail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 1.25rem;
  margin-bottom: 1.25rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid #e2e8f0;
}
:root.dark .cp-mail-header {
  border-color: #334155;
  color: #f1f5f9;
}
.cp-mail-main-title {
  font-size: 1.55rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 0.35rem;
}
:root.dark .cp-mail-main-title {
  color: #f8fafc;
}
.cp-mail-crumbs {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  margin-bottom: 0.5rem;
}
.crumb-link {
  color: #0284c7;
  cursor: pointer;
  text-decoration: none;
}
.crumb-link:hover {
  text-decoration: underline;
}
.crumb-link.active {
  color: #64748b;
  cursor: default;
  text-decoration: none;
}
:root.dark .crumb-link.active {
  color: #94a3b8;
}
.crumb-sep {
  color: #94a3b8;
}
.cp-mail-desc {
  font-size: 0.85rem;
  color: #475569;
  margin: 0;
}
:root.dark .cp-mail-desc {
  color: #94a3b8;
}
.cp-inline-link {
  color: #0284c7;
  text-decoration: none;
}
.cp-inline-link:hover {
  text-decoration: underline;
}

/* Stat Box (32 Available | 8 Used) */
.cp-stat-box {
  display: flex;
  align-items: center;
  border: 1px solid #cbd5e1;
  border-radius: 0.375rem;
  background: #fff;
  padding: 0.6rem 1.1rem;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
:root.dark .cp-stat-box {
  background: #1e293b;
  border-color: #334155;
}
.stat-cell {
  display: flex;
  align-items: baseline;
  gap: 0.35rem;
}
.stat-num {
  font-size: 1.35rem;
  font-weight: 700;
  color: #0f172a;
}
:root.dark .stat-num {
  color: #f8fafc;
}
.stat-lbl {
  font-size: 0.8rem;
  color: #64748b;
}
:root.dark .stat-lbl {
  color: #94a3b8;
}
.stat-divider {
  width: 1px;
  height: 1.75rem;
  background: #e2e8f0;
  margin: 0 1rem;
}
:root.dark .stat-divider {
  background: #334155;
}

/* Alert Banner */
.cp-alert-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: 0.375rem;
  margin-bottom: 1.25rem;
  font-size: 0.86rem;
}
.cp-alert-success {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
}
:root.dark .cp-alert-success {
  background: #14532d/40;
  border-color: #166534;
  color: #86efac;
}
.cp-alert-error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}
:root.dark .cp-alert-error {
  background: #7f1d1d/40;
  border-color: #991b1b;
  color: #fca5a5;
}
.cp-alert-close {
  margin-left: auto;
  background: none;
  border: none;
  font-size: 1.25rem;
  cursor: pointer;
  color: inherit;
  opacity: 0.7;
}
.cp-alert-close:hover {
  opacity: 1;
}

/* Search and Filters */
.cp-search-filters-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}
.cp-search-wrap {
  display: flex;
  align-items: center;
  max-width: 280px;
  width: 100%;
}
.cp-search-input {
  flex: 1;
  border: 1px solid #cbd5e1;
  border-radius: 0.25rem 0 0 0.25rem;
  padding: 0.4rem 0.65rem;
  font-size: 0.85rem;
  outline: none;
  background: #fff;
  color: #1e293b;
}
:root.dark .cp-search-input {
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
}
.cp-search-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-left: none;
  border-radius: 0 0.25rem 0.25rem 0;
  padding: 0.4rem 0.75rem;
  cursor: pointer;
  color: #64748b;
}
:root.dark .cp-search-btn {
  background: #334155;
  border-color: #334155;
  color: #cbd5e1;
}
.cp-filter-pills-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.filter-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: #475569;
  margin-right: 0.25rem;
}
:root.dark .filter-label {
  color: #94a3b8;
}
.cp-filter-pill {
  background: transparent;
  border: none;
  color: #0284c7;
  font-size: 0.82rem;
  padding: 0.2rem 0.45rem;
  border-radius: 0.25rem;
  cursor: pointer;
  text-decoration: none;
}
.cp-filter-pill:hover {
  text-decoration: underline;
}
.cp-filter-pill.active {
  background: #0284c7;
  color: #fff;
  font-weight: 600;
  text-decoration: none;
}
.cp-pagination-info {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
  color: #64748b;
}
.page-nav-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 0.2rem;
  padding: 0.15rem 0.4rem;
  font-size: 0.75rem;
  cursor: pointer;
  color: #64748b;
}
.page-nav-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Action Toolbar */
.cp-action-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}
.toolbar-left, .toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.cp-btn-icon-cog {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 0.25rem;
  padding: 0.45rem 0.65rem;
  cursor: pointer;
  color: #475569;
}
:root.dark .cp-btn-icon-cog {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}

/* Buttons */
.cp-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.86rem;
  font-weight: 500;
  border-radius: 0.25rem;
  padding: 0.45rem 0.95rem;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.cp-btn-primary {
  background: #0284c7;
  color: #fff;
}
.cp-btn-primary:hover:not(:disabled) {
  background: #0369a1;
}
.cp-btn-default {
  background: #fff;
  border-color: #cbd5e1;
  color: #334155;
}
:root.dark .cp-btn-default {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}
.cp-btn-default:hover:not(:disabled) {
  background: #f8fafc;
}
:root.dark .cp-btn-default:hover:not(:disabled) {
  background: #334155;
}
.cp-btn-sm {
  padding: 0.3rem 0.65rem;
  font-size: 0.8rem;
}
.cp-btn-xs {
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
}

/* Table */
.cp-table-container {
  overflow-x: auto;
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
  background: #fff;
}
:root.dark .cp-table-container {
  border-color: #334155;
  background: #0f172a;
}
.cp-email-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 0.86rem;
}
.cp-email-table th {
  background: #f8fafc;
  color: #0284c7;
  font-weight: 600;
  padding: 0.65rem 0.85rem;
  border-bottom: 2px solid #cbd5e1;
  white-space: nowrap;
}
:root.dark .cp-email-table th {
  background: #1e293b;
  border-color: #475569;
  color: #38bdf8;
}
.th-header-sort {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  cursor: pointer;
}
.cp-email-table td {
  padding: 0.75rem 0.85rem;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}
:root.dark .cp-email-table td {
  border-color: #1e293b;
}
.cp-mail-row:hover {
  background: #f8fafc;
}
:root.dark .cp-mail-row:hover {
  background: #1e293b/60;
}
.cp-mail-row.selected {
  background: #f0f9ff;
}
:root.dark .cp-mail-row.selected {
  background: #0369a1/20;
}
.th-check, .td-check {
  width: 38px;
  text-align: center;
}
.th-expand, .td-expand {
  width: 24px;
  text-align: center;
}

.account-cell {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.account-email {
  font-weight: 600;
  color: #0f172a;
}
:root.dark .account-email {
  color: #f8fafc;
}
.badge-system {
  background: #0284c7;
  color: #fff;
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 0.15rem 0.4rem;
  border-radius: 0.2rem;
}
.status-unrestricted {
  font-size: 0.82rem;
  font-weight: 500;
  color: #166534;
}
:root.dark .status-unrestricted {
  color: #86efac;
}
.status-restricted {
  font-size: 0.82rem;
  font-weight: 500;
  color: #991b1b;
}

/* Storage Bar */
.storage-cell {
  max-width: 220px;
}
.storage-text {
  display: flex;
  gap: 0.35rem;
  font-size: 0.78rem;
  color: #475569;
  margin-bottom: 0.25rem;
}
:root.dark .storage-text {
  color: #94a3b8;
}
.storage-progress-bar {
  width: 100%;
  height: 6px;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
}
:root.dark .storage-progress-bar {
  background: #334155;
}
.progress-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}

/* Action Buttons in Row */
.actions-group {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.cp-btn-action {
  background: #fff;
  border: 1px solid #cbd5e1;
  color: #0284c7;
  font-size: 0.78rem;
  font-weight: 500;
  padding: 0.25rem 0.6rem;
  border-radius: 0.25rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  transition: all 0.15s ease;
}
:root.dark .cp-btn-action {
  background: #1e293b;
  border-color: #334155;
  color: #38bdf8;
}
.cp-btn-action:hover {
  background: #f0f9ff;
  border-color: #0284c7;
}

/* ================================================================= */
/* CREATE AN EMAIL ACCOUNT FORM & SIDEBAR (Image 7) */
/* ================================================================= */
.cp-create-grid {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 1.5rem;
  align-items: start;
}
@media (max-width: 900px) {
  .cp-create-grid {
    grid-template-columns: 1fr;
  }
}
.cp-create-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
  padding: 1.5rem;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}
:root.dark .cp-create-card {
  background: #0f172a;
  border-color: #334155;
}
.card-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 0.75rem;
  margin-bottom: 1.25rem;
}
:root.dark .card-top-bar {
  border-color: #334155;
}
.card-heading {
  font-size: 0.95rem;
  font-weight: 700;
  color: #334155;
  letter-spacing: 0.04em;
  margin: 0;
}
:root.dark .card-heading {
  color: #cbd5e1;
}
.btn-help-toggle {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 0.25rem;
  padding: 0.25rem 0.55rem;
  font-size: 0.78rem;
  color: #475569;
  cursor: pointer;
}
:root.dark .btn-help-toggle {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}

.form-group {
  margin-bottom: 1.25rem;
}
.form-label {
  display: block;
  font-size: 0.86rem;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 0.35rem;
}
:root.dark .form-label {
  color: #f1f5f9;
}
.form-sub-hint {
  font-size: 0.78rem;
  color: #64748b;
  margin: 0.35rem 0 0;
}
:root.dark .form-sub-hint {
  color: #94a3b8;
}
.cp-select, .cp-input {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 0.25rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.86rem;
  background: #fff;
  color: #1e293b;
  outline: none;
}
:root.dark .cp-select, :root.dark .cp-input {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}
.cp-input-sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.8rem;
}

/* Username input with suffix */
.cp-addon-input-wrap {
  display: flex;
  align-items: center;
  width: 100%;
}
.cp-addon-input {
  flex: 1;
  border: 1px solid #cbd5e1;
  border-radius: 0.25rem 0 0 0.25rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.86rem;
  background: #fff;
  color: #1e293b;
  outline: none;
}
:root.dark .cp-addon-input {
  background: #1e293b;
  border-color: #334155;
  color: #f8fafc;
}
.cp-addon-suffix {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-left: none;
  border-radius: 0 0.25rem 0.25rem 0;
  padding: 0.5rem 0.75rem;
  font-size: 0.86rem;
  font-family: monospace;
  color: #475569;
}
:root.dark .cp-addon-suffix {
  background: #334155;
  border-color: #334155;
  color: #cbd5e1;
}

/* Radio stack */
.radio-options-stack {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  margin-top: 0.35rem;
}
.radio-item, .checkbox-item {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.86rem;
  color: #334155;
  cursor: pointer;
}
:root.dark .radio-item, :root.dark .checkbox-item {
  color: #cbd5e1;
}

/* Password group with eye and generate */
.password-input-group {
  display: flex;
  align-items: center;
  position: relative;
}
.password-input-group .cp-input {
  padding-right: 140px;
}
.btn-eye-toggle {
  position: absolute;
  right: 90px;
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.4rem;
}
.btn-generate-password {
  position: absolute;
  right: 6px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 0.2rem;
  padding: 0.25rem 0.55rem;
  font-size: 0.78rem;
  font-weight: 500;
  color: #334155;
  cursor: pointer;
}
:root.dark .btn-generate-password {
  background: #334155;
  border-color: #475569;
  color: #cbd5e1;
}

/* Strength meter */
.strength-meter-wrap {
  width: 100%;
}
.strength-bar-track {
  width: 100%;
  height: 6px;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
}
:root.dark .strength-bar-track {
  background: #334155;
}
.strength-bar-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}

/* Optional Settings */
.optional-settings-box {
  border: 1px solid #e2e8f0;
  border-radius: 0.25rem;
  margin-top: 1.5rem;
}
:root.dark .optional-settings-box {
  border-color: #334155;
}
.opt-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.65rem 0.85rem;
  background: #f8fafc;
  cursor: pointer;
}
:root.dark .opt-head {
  background: #1e293b;
}
.opt-title {
  font-size: 0.86rem;
  font-weight: 600;
  color: #334155;
}
:root.dark .opt-title {
  color: #cbd5e1;
}
.opt-body {
  padding: 1rem;
  background: #fff;
  border-top: 1px solid #e2e8f0;
}
:root.dark .opt-body {
  background: #0f172a;
  border-color: #334155;
}

/* Right Sidebar (Image 7) */
.cp-create-sidebar {
  display: flex;
  flex-direction: column;
}
.sidebar-info-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
  background: #fff;
  padding: 1.1rem;
}
:root.dark .sidebar-info-card {
  background: #0f172a;
  border-color: #334155;
}
.side-card-title {
  font-size: 0.82rem;
  font-weight: 700;
  color: #334155;
  letter-spacing: 0.05em;
  margin: 0 0 0.5rem;
}
:root.dark .side-card-title {
  color: #cbd5e1;
}
.side-card-text {
  font-size: 0.82rem;
  color: #64748b;
  margin: 0 0 0.85rem;
  line-height: 1.4;
}
:root.dark .side-card-text {
  color: #94a3b8;
}
.side-card-btn, .side-card-link {
  display: inline-flex;
  align-items: center;
  font-size: 0.82rem;
  font-weight: 600;
  color: #0284c7;
  background: none;
  border: none;
  cursor: pointer;
  text-decoration: none;
  padding: 0;
}
.side-card-btn:hover, .side-card-link:hover {
  text-decoration: underline;
}

/* Modals */
.cp-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: 1rem;
}
.cp-modal-box {
  background: #fff;
  border-radius: 0.5rem;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
  width: 100%;
  max-width: 520px;
  overflow: hidden;
  border: 1px solid #cbd5e1;
}
:root.dark .cp-modal-box {
  background: #0f172a;
  border-color: #334155;
}
.cp-modal-wide {
  max-width: 680px;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.85rem 1.25rem;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
:root.dark .modal-head {
  background: #1e293b;
  border-color: #334155;
}
.modal-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}
:root.dark .modal-title {
  color: #f8fafc;
}
.modal-close-btn {
  background: none;
  border: none;
  font-size: 1.4rem;
  color: #64748b;
  cursor: pointer;
}
.modal-body {
  padding: 1.25rem;
}
.modal-footer {
  display: flex;
  justify-content: flex-end;
  padding: 0.85rem 1.25rem;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
}
:root.dark .modal-footer {
  background: #1e293b;
  border-color: #334155;
}

.settings-box {
  padding: 1rem;
  border-radius: 0.375rem;
  border: 1px solid #cbd5e1;
}
.secure-box {
  background: #f0fdf4;
  border-color: #86efac;
}
:root.dark .secure-box {
  background: #14532d/30;
  border-color: #166534;
}
.box-title {
  margin: 0 0 0.75rem;
  font-size: 0.9rem;
}
.settings-dl {
  display: grid;
  grid-template-columns: 140px 1fr;
  row-gap: 0.5rem;
  font-size: 0.85rem;
}
.settings-dl dt {
  font-weight: 600;
  color: #475569;
}
:root.dark .settings-dl dt {
  color: #94a3b8;
}
.settings-dl dd {
  margin: 0;
  color: #0f172a;
}
:root.dark .settings-dl dd {
  color: #f8fafc;
}
</style>
