<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { customersApi } from '@/api'
import { isCustomerCpanelHost, tenantCpanelUrl } from '@/lib/platformHosts'

export interface DomainItem {
  id: string
  domain_name: string
  domain_type: string
  document_root: string
  full_document_root: string
  redirects_to?: string | null
  force_https: boolean
  is_primary: boolean
  ssl_active: boolean
  can_delete: boolean
  created_at?: string | null
}

const props = defineProps<{
  environmentId: string
  canRedirects?: boolean
  canGit?: boolean
  reposLimit?: number | null
  mailboxesLimit?: number | null
}>()

// Navigation state: 'list' | 'create' | 'manage' | 'redirects' | 'dns' | 'git'
const currentView = ref<'list' | 'create' | 'manage' | 'redirects' | 'dns' | 'git'>('list')
const selectedDomain = ref<DomainItem | null>(null)

// Domains list data
const loading = ref(true)
const busy = ref(false)
const msg = ref<{ type: 'ok' | 'err'; text: string } | null>(null)

const primaryDomain = ref('')
const unixUsername = ref('')
const homeDir = ref('')
const defaultDocRoot = ref('/public_html')
const packageSupported = ref(true)
const customDomainsLimit = ref<number | null>(null)
const customDomainsCount = ref(0)
const domainItems = ref<DomainItem[]>([])

const searchQuery = ref('')
const selectedDomainIds = ref<Set<string>>(new Set())

// Sorting state
const sortBy = ref<'domain' | 'docroot' | 'redirects' | 'https'>('domain')
const sortOrder = ref<'asc' | 'desc'>('asc')

function toggleSort(col: 'domain' | 'docroot' | 'redirects' | 'https') {
  if (sortBy.value === col) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = col
    sortOrder.value = 'asc'
  }
}

// Create Domain Form
const createDomainType = ref<'registered' | 'temporary'>('registered')
const newDomainName = ref('')
const shareDocRoot = ref(true)
const customDocRoot = ref('')
const newForceHttps = ref(true)

// Manage Domain Form
const editDocRoot = ref('')
const editRedirectUrl = ref('')
const editForceHttps = ref(true)

// Redirects, DNS, Git state
const redirectsOn = computed(() => props.canRedirects !== false)
const gitOn = computed(() => props.canGit !== false)

const redirects = ref<Array<{ id: string; source_path: string; target_url: string; status_code: number }>>([])
const zone = ref<{
  editable: boolean
  included_hostname: boolean
  message: string
  records: Array<{ id: string; record_type: string; host: string; value: string; ttl: number }>
} | null>(null)
const git = ref<{
  configured: boolean
  branch?: string | null
  commit?: string | null
  remote?: string | null
  message?: string
} | null>(null)

const redirSource = ref('/blog')
const redirTarget = ref('https://')
const redirCode = ref(301)
const zoneType = ref('CNAME')
const zoneHost = ref('www')
const zoneValue = ref('')
const gitUrl = ref('')
const gitBranch = ref('main')

// Auto-fill custom document root when domain name changes in create form
watch(newDomainName, (val) => {
  if (!shareDocRoot.value && !customDocRoot.value) {
    const clean = val.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/.*$/, '')
    if (clean) {
      customDocRoot.value = clean
    }
  }
})

watch(shareDocRoot, (isShared) => {
  if (!isShared && !customDocRoot.value && newDomainName.value) {
    const clean = newDomainName.value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/.*$/, '')
    customDocRoot.value = clean
  }
})

const filteredDomains = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  let list = domainItems.value
  if (q) {
    list = list.filter(
      (d) =>
        d.domain_name.toLowerCase().includes(q) ||
        d.document_root.toLowerCase().includes(q) ||
        (d.redirects_to && d.redirects_to.toLowerCase().includes(q)),
    )
  }

  return [...list].sort((a, b) => {
    if (sortBy.value === 'domain') {
      if (a.is_primary && !b.is_primary) return sortOrder.value === 'asc' ? -1 : 1
      if (!a.is_primary && b.is_primary) return sortOrder.value === 'asc' ? 1 : -1
      const cmp = a.domain_name.localeCompare(b.domain_name)
      return sortOrder.value === 'asc' ? cmp : -cmp
    }
    if (sortBy.value === 'docroot') {
      const cmp = a.document_root.localeCompare(b.document_root)
      return sortOrder.value === 'asc' ? cmp : -cmp
    }
    if (sortBy.value === 'redirects') {
      const rA = a.redirects_to || 'Not Redirected'
      const rB = b.redirects_to || 'Not Redirected'
      const cmp = rA.localeCompare(rB)
      return sortOrder.value === 'asc' ? cmp : -cmp
    }
    if (sortBy.value === 'https') {
      const hA = a.force_https ? 1 : 0
      const hB = b.force_https ? 1 : 0
      return sortOrder.value === 'asc' ? hB - hA : hA - hB
    }
    return 0
  })
})

const isAllSelected = computed(() => {
  return filteredDomains.value.length > 0 && filteredDomains.value.every((d) => selectedDomainIds.value.has(d.id))
})

function toggleSelectAll() {
  if (isAllSelected.value) {
    selectedDomainIds.value.clear()
  } else {
    for (const d of filteredDomains.value) {
      selectedDomainIds.value.add(d.id)
    }
  }
}

function toggleSelect(id: string) {
  if (selectedDomainIds.value.has(id)) {
    selectedDomainIds.value.delete(id)
  } else {
    selectedDomainIds.value.add(id)
  }
}

async function load() {
  if (!props.environmentId) {
    loading.value = false
    return
  }
  loading.value = true
  msg.value = null
  try {
    const [dRes, rRes, zRes, gRes] = await Promise.allSettled([
      customersApi.listEnvDomainItems(props.environmentId),
      customersApi.listEnvRedirects(props.environmentId),
      customersApi.getEnvZone(props.environmentId),
      customersApi.getEnvGit(props.environmentId),
    ])

    if (dRes.status === 'fulfilled' && dRes.value.data) {
      const data = dRes.value.data
      primaryDomain.value = data.primary_domain || ''
      unixUsername.value = data.unix_username || ''
      homeDir.value = data.home_dir || `/home3/${data.unix_username || 'user'}`
      defaultDocRoot.value = data.default_doc_root || '/public_html'
      packageSupported.value = data.package_supported !== false
      customDomainsLimit.value = data.custom_domains_limit ?? null
      customDomainsCount.value = data.custom_domains_count ?? 0
      domainItems.value = data.items || []
    } else if (dRes.status === 'rejected') {
      const err = dRes.reason as { response?: { data?: { error?: { message?: string } } }; message?: string }
      msg.value = {
        type: 'err',
        text: err?.response?.data?.error?.message ?? err?.message ?? 'Could not load domain list.',
      }
    }

    if (rRes.status === 'fulfilled' && rRes.value.data) {
      redirects.value = rRes.value.data || []
    }
    if (zRes.status === 'fulfilled' && zRes.value.data) {
      zone.value = zRes.value.data
    }
    if (gRes.status === 'fulfilled' && gRes.value.data) {
      git.value = gRes.value.data
    }
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Could not load domains.' }
  } finally {
    loading.value = false
  }
}

function openCreateDomain() {
  newDomainName.value = ''
  shareDocRoot.value = true
  customDocRoot.value = ''
  createDomainType.value = 'registered'
  newForceHttps.value = true
  msg.value = null
  currentView.value = 'create'
}

function openManageDomain(domain: DomainItem) {
  selectedDomain.value = domain
  editDocRoot.value = domain.document_root.replace(/^\//, '')
  editRedirectUrl.value = domain.redirects_to || ''
  editForceHttps.value = domain.force_https
  msg.value = null
  currentView.value = 'manage'
}

function returnToList() {
  currentView.value = 'list'
  selectedDomain.value = null
  msg.value = null
}

async function handleCreateDomain(keepOpen = false) {
  const dom = newDomainName.value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/.*$/, '')
  if (!dom) {
    msg.value = { type: 'err', text: 'Please enter a valid domain or subdomain name.' }
    return
  }

  busy.value = true
  msg.value = null
  try {
    await customersApi.createEnvDomainItem(props.environmentId, {
      domain_name: dom,
      domain_type: createDomainType.value,
      share_document_root: shareDocRoot.value,
      document_root: shareDocRoot.value ? null : customDocRoot.value.trim() || dom,
      force_https: newForceHttps.value,
    })
    msg.value = { type: 'ok', text: `Domain "${dom}" was successfully created.` }
    await load()
    if (keepOpen) {
      newDomainName.value = ''
      customDocRoot.value = ''
    } else {
      currentView.value = 'list'
    }
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Could not create domain.' }
  } finally {
    busy.value = false
  }
}

async function handleUpdateDomain() {
  if (!selectedDomain.value) return
  busy.value = true
  msg.value = null
  try {
    const updated = await customersApi.updateEnvDomainItem(props.environmentId, selectedDomain.value.id, {
      document_root: editDocRoot.value.trim() || null,
      force_https: editForceHttps.value,
      redirects_to: editRedirectUrl.value.trim() || null,
    })
    msg.value = { type: 'ok', text: `Domain "${selectedDomain.value.domain_name}" updated successfully.` }
    if (updated.data) {
      selectedDomain.value = updated.data
    }
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Could not update domain.' }
  } finally {
    busy.value = false
  }
}

async function handleDeleteDomain(domain: DomainItem) {
  if (domain.is_primary) {
    alert('The primary domain for this hosting account cannot be removed.')
    return
  }
  if (!confirm(`Are you sure you want to remove the "${domain.domain_name}" domain? This will delete the domain configuration, but your files in ${domain.document_root} will NOT be deleted.`)) {
    return
  }
  busy.value = true
  msg.value = null
  try {
    await customersApi.deleteEnvDomainItem(props.environmentId, domain.id)
    msg.value = { type: 'ok', text: `Domain "${domain.domain_name}" has been removed.` }
    await load()
    if (currentView.value === 'manage') {
      currentView.value = 'list'
    }
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Could not delete domain.' }
  } finally {
    busy.value = false
  }
}

async function toggleHttpsRedirect(domain: DomainItem) {
  const nextVal = !domain.force_https
  domain.force_https = nextVal
  try {
    await customersApi.updateEnvDomainItem(props.environmentId, domain.id, {
      force_https: nextVal,
    })
  } catch {
    domain.force_https = !nextVal
  }
}

async function toggleSelectedHttps(forceState: boolean) {
  if (!selectedDomainIds.value.size) return
  busy.value = true
  try {
    const promises = Array.from(selectedDomainIds.value).map((id) =>
      customersApi.updateEnvDomainItem(props.environmentId, id, { force_https: forceState }),
    )
    await Promise.allSettled(promises)
    await load()
  } finally {
    busy.value = false
  }
}

function openFileManager(path: string) {
  const clean = path.replace(/^\//, '')
  const q = clean && clean !== 'public_html' ? `?path=${encodeURIComponent(clean)}` : ''
  if (isCustomerCpanelHost()) {
    window.open(`/files${q}`, '_blank')
    return
  }
  const customUrl = primaryDomain.value ? tenantCpanelUrl(primaryDomain.value, 'files') : null
  if (customUrl) {
    window.open(`${customUrl}${q}`, '_blank')
    return
  }
  window.open(`/hosting/${encodeURIComponent(props.environmentId)}/files${q}`, '_blank')
}

// Redirects actions
async function addRedirect() {
  if (!redirectsOn.value) return
  busy.value = true
  msg.value = null
  try {
    await customersApi.createEnvRedirect(props.environmentId, {
      source_path: redirSource.value.trim(),
      target_url: redirTarget.value.trim(),
      status_code: redirCode.value,
    })
    const r = await customersApi.listEnvRedirects(props.environmentId)
    redirects.value = r.data || []
    msg.value = { type: 'ok', text: 'Redirect saved.' }
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Could not create redirect.' }
  } finally {
    busy.value = false
  }
}

async function removeRedirect(id: string) {
  busy.value = true
  try {
    await customersApi.deleteEnvRedirect(props.environmentId, id)
    const r = await customersApi.listEnvRedirects(props.environmentId)
    redirects.value = r.data || []
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Could not remove redirect.' }
  } finally {
    busy.value = false
  }
}

// DNS Zone actions
async function addZone() {
  busy.value = true
  msg.value = null
  try {
    await customersApi.createEnvZoneRecord(props.environmentId, {
      record_type: zoneType.value,
      host: zoneHost.value.trim() || '@',
      value: zoneValue.value.trim(),
    })
    zoneValue.value = ''
    const z = await customersApi.getEnvZone(props.environmentId)
    zone.value = z.data
    msg.value = { type: 'ok', text: 'DNS record saved.' }
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Could not add DNS record.' }
  } finally {
    busy.value = false
  }
}

// Git actions
async function cloneGit() {
  if (!gitOn.value) return
  busy.value = true
  msg.value = null
  try {
    const { data } = await customersApi.cloneEnvGit(props.environmentId, {
      repo_url: gitUrl.value.trim(),
      branch: gitBranch.value.trim() || undefined,
    })
    git.value = data
    msg.value = { type: 'ok', text: data.message || 'Repository cloned.' }
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Clone failed.' }
  } finally {
    busy.value = false
  }
}

async function pullGit() {
  busy.value = true
  msg.value = null
  try {
    const { data } = await customersApi.pullEnvGit(props.environmentId)
    git.value = data
    msg.value = { type: 'ok', text: data.message || 'Pulled updates.' }
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = { type: 'err', text: x.response?.data?.error?.message ?? 'Pull failed.' }
  } finally {
    busy.value = false
  }
}

watch(() => props.environmentId, (id) => {
  if (id) void load()
})

onMounted(load)
</script>

<template>
  <div class="cp-domains-wrap">
    <!-- Header with Search and Quick Links -->
    <div class="cp-domains-header">
      <div class="cp-title-area">
        <h1 class="cp-page-title">Domains</h1>
        <nav v-if="currentView !== 'list'" class="cp-breadcrumbs" aria-label="Breadcrumb">
          <a href="#" class="crumb-link" @click.prevent="returnToList">List Domains</a>
          <span class="crumb-sep">/</span>
          <span v-if="currentView === 'create'" class="crumb-current">Create a New Domain</span>
          <span v-else-if="currentView === 'manage'" class="crumb-current">Manage the Domain</span>
          <span v-else-if="currentView === 'redirects'" class="crumb-current">Redirects</span>
          <span v-else-if="currentView === 'dns'" class="crumb-current">Zone Editor</span>
          <span v-else-if="currentView === 'git'" class="crumb-current">Git™ Version Control</span>
        </nav>
      </div>
      <p class="cp-doc-hint">
        Use this interface to manage your domains. For more information, read the
        <a href="https://ifnotus.space" target="_blank" rel="noopener" class="cp-doc-link">documentation</a>.
      </p>
    </div>

    <!-- Feedback Message Alert -->
    <div v-if="msg" class="cp-alert" :class="msg.type">
      <i class="fas" :class="msg.type === 'ok' ? 'fa-check-circle' : 'fa-exclamation-circle'" />
      <span>{{ msg.text }}</span>
      <button type="button" class="cp-alert-close" @click="msg = null">&times;</button>
    </div>

    <!-- Sub-tab Navigation (Domains / Redirects / Zone Editor / Git) -->
    <div class="cp-subnav-bar">
      <button
        type="button"
        class="cp-subnav-btn"
        :class="{ active: currentView === 'list' || currentView === 'create' || currentView === 'manage' }"
        @click="currentView = 'list'"
      >
        <i class="fas fa-globe" /> Domains
      </button>
      <button
        type="button"
        class="cp-subnav-btn"
        :class="{ active: currentView === 'redirects' }"
        @click="currentView = 'redirects'"
      >
        <i class="fas fa-directions" /> Redirects
      </button>
      <button
        type="button"
        class="cp-subnav-btn"
        :class="{ active: currentView === 'dns' }"
        @click="currentView = 'dns'"
      >
        <i class="fas fa-server" /> Zone Editor (DNS)
      </button>
      <button
        v-if="gitOn"
        type="button"
        class="cp-subnav-btn"
        :class="{ active: currentView === 'git' }"
        @click="currentView = 'git'"
      >
        <i class="fab fa-git-alt" /> Git™ Version Control
      </button>
    </div>

    <!-- VIEW 1: LIST DOMAINS -->
    <div v-if="currentView === 'list'" class="cp-view-list">
      <!-- Search and Item Count Bar -->
      <div class="cp-list-top-bar">
        <div class="cp-search-box">
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Search"
            class="cp-search-input"
            aria-label="Search domains"
          />
          <button type="button" class="cp-search-btn" aria-label="Search">
            <i class="fas fa-search" />
          </button>
        </div>
        <div class="cp-display-count">
          Displaying {{ filteredDomains.length ? 1 : 0 }} through {{ filteredDomains.length }} out of {{ domainItems.length }} items
        </div>
      </div>

      <!-- Action Toolbar -->
      <div class="cp-toolbar-bar">
        <div class="cp-toolbar-left">
          <label class="cp-checkbox-label">
            <input
              type="checkbox"
              :checked="isAllSelected"
              @change="toggleSelectAll"
            />
          </label>
          <div class="cp-btn-dropdown">
            <button
              type="button"
              class="cp-btn cp-btn-default cp-btn-sm"
              :disabled="!selectedDomainIds.size || busy"
              @click="toggleSelectedHttps(true)"
            >
              Enable Force HTTPS Redirect <i class="fas fa-caret-down ml-1" />
            </button>
          </div>
        </div>
        <div class="cp-toolbar-right">
          <button
            type="button"
            class="cp-btn cp-btn-primary"
            @click="openCreateDomain"
          >
            Create A New Domain
          </button>
        </div>
      </div>

      <!-- Main Domains Data Table -->
      <div class="cp-table-container">
        <table class="cp-domains-table">
          <thead>
            <tr>
              <th class="th-check">
                <input
                  type="checkbox"
                  :checked="isAllSelected"
                  @change="toggleSelectAll"
                />
              </th>
              <th class="th-sortable" @click="toggleSort('domain')">
                <div class="th-content">
                  <span>Domain</span>
                  <i
                    class="fas cp-sort-icon"
                    :class="sortBy === 'domain' ? (sortOrder === 'asc' ? 'fa-caret-up active' : 'fa-caret-down active') : 'fa-sort'"
                  />
                </div>
              </th>
              <th class="th-sortable" @click="toggleSort('docroot')">
                <div class="th-content">
                  <span>Document Root</span>
                  <i
                    class="fas cp-sort-icon"
                    :class="sortBy === 'docroot' ? (sortOrder === 'asc' ? 'fa-caret-up active' : 'fa-caret-down active') : 'fa-sort'"
                  />
                </div>
              </th>
              <th class="th-sortable" @click="toggleSort('redirects')">
                <div class="th-content">
                  <span>Redirects To</span>
                  <i
                    class="fas cp-sort-icon"
                    :class="sortBy === 'redirects' ? (sortOrder === 'asc' ? 'fa-caret-up active' : 'fa-caret-down active') : 'fa-sort'"
                  />
                </div>
              </th>
              <th class="th-sortable" @click="toggleSort('https')">
                <div class="th-content">
                  <span>Force HTTPS Redirect</span>
                  <i
                    class="fas cp-sort-icon"
                    :class="sortBy === 'https' ? (sortOrder === 'asc' ? 'fa-caret-up active' : 'fa-caret-down active') : 'fa-sort'"
                  />
                </div>
              </th>
              <th class="th-actions">
                <span>Actions</span>
                <i class="fas fa-cog text-slate-400 ml-1" />
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading" class="tr-empty">
              <td colspan="6" class="td-loading">
                <i class="fas fa-spinner fa-spin" /> Loading domains…
              </td>
            </tr>
            <tr v-else-if="!filteredDomains.length" class="tr-empty">
              <td colspan="6" class="td-no-records">
                No domains found. Click <strong>"Create A New Domain"</strong> to add an addon domain or subdomain.
              </td>
            </tr>
            <tr
              v-for="d in filteredDomains"
              :key="d.id"
              class="cp-domain-row"
              :class="{ selected: selectedDomainIds.has(d.id) }"
            >
              <td class="td-check">
                <input
                  type="checkbox"
                  :checked="selectedDomainIds.has(d.id)"
                  @change="toggleSelect(d.id)"
                />
              </td>
              <td class="td-domain">
                <div class="domain-name-cell">
                  <a
                    :href="`http://${d.domain_name}`"
                    target="_blank"
                    rel="noopener"
                    class="domain-link"
                  >
                    <i class="fas fa-external-link-alt domain-ext-icon" />
                    <span>{{ d.domain_name }}</span>
                  </a>
                  <span v-if="d.is_primary" class="badge-primary-dom">Main Domain</span>
                </div>
              </td>
              <td class="td-docroot">
                <button
                  type="button"
                  class="docroot-link-btn"
                  title="Open in File Manager"
                  @click="openFileManager(d.document_root)"
                >
                  <i class="fas fa-home text-sky-600 mr-1" />
                  <span>{{ d.document_root }}</span>
                </button>
              </td>
              <td class="td-redirects">
                <span v-if="!d.redirects_to" class="text-slate-600 dark:text-slate-400">Not Redirected</span>
                <a
                  v-else
                  :href="d.redirects_to"
                  target="_blank"
                  rel="noopener"
                  class="redirect-link"
                >
                  {{ d.redirects_to }}
                </a>
              </td>
              <td class="td-https">
                <div class="https-toggle-wrapper">
                  <button
                    type="button"
                    class="cp-switch"
                    :class="{ on: d.force_https }"
                    :aria-label="`Toggle HTTPS redirect for ${d.domain_name}`"
                    @click="toggleHttpsRedirect(d)"
                  >
                    <span class="cp-switch-knob" />
                  </button>
                  <span class="https-label font-medium" :class="d.force_https ? 'text-sky-600 font-bold' : 'text-slate-500'">
                    {{ d.force_https ? 'On' : 'Off' }}
                  </span>
                </div>
              </td>
              <td class="td-actions">
                <div class="actions-btn-group">
                  <button
                    type="button"
                    class="cp-btn cp-btn-action"
                    @click="openManageDomain(d)"
                  >
                    <i class="fas fa-wrench" /> Manage
                  </button>
                  <a
                    :href="isCustomerCpanelHost() ? '/mail' : `/hosting/${encodeURIComponent(environmentId)}/mail`"
                    class="cp-btn cp-btn-action"
                  >
                    <i class="fas fa-envelope" /> Create Email
                  </a>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- VIEW 2: CREATE A NEW DOMAIN -->
    <div v-else-if="currentView === 'create'" class="cp-view-create">
      <div class="cp-card cp-form-card">
        <div class="cp-card-header">
          <h2 class="cp-card-title">Create a New Domain</h2>
        </div>
        <div class="cp-card-body">
          <!-- Domain Type Selection -->
          <div class="cp-form-group">
            <label class="cp-label cp-label-bold">Select the type of domain to create</label>
            <div class="cp-radio-list">
              <label class="cp-radio-option">
                <input
                  v-model="createDomainType"
                  type="radio"
                  value="registered"
                  name="domainType"
                />
                <div class="radio-desc-box">
                  <strong class="radio-title">Registered Domain</strong>
                  <p class="radio-sub">
                    Add a registered domain as an addon domain or domain alias. You can also create a subdomain for an existing domain.
                  </p>
                </div>
              </label>

              <label class="cp-radio-option">
                <input
                  v-model="createDomainType"
                  type="radio"
                  value="temporary"
                  name="domainType"
                />
                <div class="radio-desc-box">
                  <strong class="radio-title">Temporary Domain</strong>
                  <p class="radio-sub">
                    A temporary domain allows you to create and view your website before you add a registered domain.
                  </p>
                </div>
              </label>
            </div>
          </div>

          <!-- Domain Name Input -->
          <div class="cp-form-group">
            <label class="cp-label cp-label-bold flex-center">
              <span>Domain</span>
              <span class="cp-help-icon" title="Enter the domain or subdomain name (e.g. blog.example.com or newbrand.com)">
                <i class="fas fa-question-circle" />
              </span>
            </label>
            <p class="cp-input-prompt">Enter the domain that you would like to create:</p>
            <input
              v-model="newDomainName"
              type="text"
              class="cp-text-input"
              placeholder="my.example.com"
              required
            />
          </div>

          <!-- Share Document Root Checkbox -->
          <div class="cp-form-group">
            <label class="cp-checkbox-option">
              <input
                v-model="shareDocRoot"
                type="checkbox"
              />
              <div class="checkbox-desc-box">
                <span class="checkbox-title">
                  Share document root ({{ homeDir }}{{ defaultDocRoot }}) with "{{ primaryDomain || 'main site' }}".
                  <span class="cp-help-icon inline ml-1" title="If checked, this domain will serve the exact same files as the primary website.">
                    <i class="fas fa-question-circle" />
                  </span>
                </span>
                <p class="checkbox-sub">
                  If the document root is shared then the created domain will serve the same content as "{{ primaryDomain }}". This setting is permanent.
                </p>
              </div>
            </label>
          </div>

          <!-- Custom Document Root Input (Shown when shareDocRoot is false) -->
          <div v-if="!shareDocRoot" class="cp-form-group cp-fade-in">
            <label class="cp-label cp-label-bold flex-center">
              <span>Document Root</span>
              <span class="cp-help-icon" title="Directory path where files for this domain will reside relative to your home folder">
                <i class="fas fa-question-circle" />
              </span>
            </label>
            <p class="cp-input-prompt">Specify the directory where you want files for this domain to exist:</p>
            <div class="cp-input-with-icon">
              <span class="input-addon-icon"><i class="fas fa-home" /></span>
              <input
                v-model="customDocRoot"
                type="text"
                class="cp-text-input"
                :placeholder="newDomainName ? newDomainName.trim().toLowerCase() : 'public_html/subfolder'"
              />
            </div>
            <p class="cp-input-hint">
              Target path: <code>{{ homeDir }}/{{ customDocRoot || newDomainName || 'subdomain' }}</code>
            </p>
          </div>

          <!-- Package Limit Notice / Support -->
          <div v-if="!packageSupported || (customDomainsLimit !== null && customDomainsCount >= customDomainsLimit)" class="cp-package-banner">
            <i class="fas fa-info-circle text-amber-500" />
            <div>
              <strong>Package Limit Notice:</strong>
              Your current hosting plan allows up to {{ customDomainsLimit ?? 0 }} addon domain(s).
              <a href="https://ifnotus.space/account?tab=billing" target="_blank" rel="noopener" class="cp-upgrade-link">
                Upgrade your plan
              </a>
              to add unlimited domains and subdomains.
            </div>
          </div>

          <!-- Action Buttons -->
          <div class="cp-form-actions">
            <button
              type="button"
              class="cp-btn cp-btn-primary"
              :disabled="busy || !newDomainName.trim()"
              @click="handleCreateDomain(false)"
            >
              <i v-if="busy" class="fas fa-spinner fa-spin mr-1" />
              <span>Submit</span>
            </button>
            <button
              type="button"
              class="cp-btn cp-btn-default"
              :disabled="busy || !newDomainName.trim()"
              @click="handleCreateDomain(true)"
            >
              Submit And Create Another
            </button>
            <a href="#" class="cp-return-link" @click.prevent="returnToList">
              <i class="fas fa-reply mr-1" /> Return To Domains
            </a>
          </div>
        </div>
      </div>
    </div>

    <!-- VIEW 3: MANAGE THE DOMAIN -->
    <div v-else-if="currentView === 'manage' && selectedDomain" class="cp-view-manage">
      <div class="cp-manage-title-wrap">
        <h2 class="cp-manage-heading">
          Manage the "{{ selectedDomain.domain_name }}" Domain
        </h2>
      </div>

      <div class="cp-manage-layout">
        <!-- Left Column: Update & Remove Cards -->
        <div class="cp-manage-col-left">
          <!-- Update Card -->
          <div class="cp-card cp-manage-card">
            <div class="cp-card-header">
              <h3 class="cp-card-section-title">UPDATE THE DOMAIN</h3>
            </div>
            <div class="cp-card-body">
              <div class="cp-form-group">
                <label class="cp-label cp-label-bold flex-center">
                  <span>New Document Root</span>
                  <span class="cp-help-icon" title="Update the folder path where files for this domain exist">
                    <i class="fas fa-question-circle" />
                  </span>
                </label>
                <p class="cp-input-prompt">Update the directory where you want the files for this domain to exist.</p>
                <div class="cp-input-with-icon">
                  <span class="input-addon-icon"><i class="fas fa-home" /></span>
                  <input
                    v-model="editDocRoot"
                    type="text"
                    class="cp-text-input"
                    placeholder="public"
                  />
                </div>
              </div>

              <div class="cp-manage-actions">
                <button
                  type="button"
                  class="cp-btn cp-btn-primary"
                  :disabled="busy"
                  @click="handleUpdateDomain"
                >
                  <i v-if="busy" class="fas fa-spinner fa-spin mr-1" />
                  <span>Update</span>
                </button>
                <a href="#" class="cp-return-link" @click.prevent="returnToList">
                  <i class="fas fa-reply mr-1" /> Return To Domains
                </a>
              </div>
            </div>
          </div>

          <!-- Remove Card (Warning Box) -->
          <div class="cp-card cp-danger-card">
            <div class="cp-card-header">
              <h3 class="cp-card-section-title text-red-600 dark:text-red-400">REMOVE THE DOMAIN</h3>
            </div>
            <div class="cp-card-body">
              <p class="cp-danger-warning">
                <strong>Warning:</strong> If you remove the "{{ selectedDomain.domain_name }}" domain, it will permanently delete the domain from your account. You cannot undo this action. This will not remove "{{ selectedDomain.domain_name }}"'s document root ({{ homeDir }}{{ selectedDomain.document_root }}).
              </p>
              <div class="mt-4">
                <button
                  type="button"
                  class="cp-btn cp-btn-danger"
                  :disabled="busy || selectedDomain.is_primary"
                  @click="handleDeleteDomain(selectedDomain)"
                >
                  <i class="fas fa-trash-alt mr-1" /> Remove Domain
                </button>
                <span v-if="selectedDomain.is_primary" class="text-xs text-slate-500 ml-2">
                  (Primary domain cannot be deleted)
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Right Column: Domain Information & Resources -->
        <div class="cp-manage-col-right">
          <div class="cp-info-sidebar">
            <h3 class="cp-sidebar-title">DOMAIN INFORMATION</h3>
            <dl class="cp-info-dl">
              <div class="info-row">
                <dt>Domain:</dt>
                <dd><strong>{{ selectedDomain.domain_name }}</strong></dd>
              </div>
              <div class="info-row">
                <dt>Redirects To:</dt>
                <dd>{{ selectedDomain.redirects_to || 'Not Redirected' }}</dd>
              </div>
              <div class="info-row">
                <dt>Document Root:</dt>
                <dd>
                  <button
                    type="button"
                    class="docroot-link-btn text-sky-600 font-semibold"
                    @click="openFileManager(selectedDomain.document_root)"
                  >
                    <i class="fas fa-home mr-1" /> {{ selectedDomain.document_root }}
                  </button>
                </dd>
              </div>
            </dl>

            <div class="cp-sidebar-section mt-6">
              <h4 class="cp-sidebar-subtitle">Additional Resources</h4>
              <ul class="cp-resource-links">
                <li>
                  <a :href="isCustomerCpanelHost() ? '/mail' : `/hosting/${encodeURIComponent(environmentId)}/mail`" class="resource-link">
                    <span>Create An Email Address</span>
                    <i class="fas fa-external-link-alt" />
                  </a>
                </li>
                <li>
                  <a href="#" class="resource-link" @click.prevent="currentView = 'redirects'">
                    <span>Modify The Redirects</span>
                    <i class="fas fa-external-link-alt" />
                  </a>
        </li>
      </ul>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- VIEW 4: REDIRECTS -->
    <div v-else-if="currentView === 'redirects'" class="cp-view-redirects">
      <div class="cp-card">
        <div class="cp-card-header">
          <h2 class="cp-card-title">Redirects</h2>
        </div>
        <div class="cp-card-body">
          <p class="muted">Send incoming requests for a specific path to another URL.</p>
          <form v-if="redirectsOn" class="form-row mt-4" @submit.prevent="addRedirect">
            <input v-model="redirSource" class="cp-text-input" placeholder="/old-path" required />
            <input v-model="redirTarget" class="cp-text-input grow" placeholder="https://newdomain.com" required />
            <select v-model.number="redirCode" class="cp-text-input">
              <option :value="301">301 (Permanent)</option>
              <option :value="302">302 (Temporary)</option>
            </select>
            <button type="submit" class="cp-btn cp-btn-primary" :disabled="busy">Add Redirect</button>
          </form>
          <p v-else class="text-amber-600 mt-2">Redirects feature is not enabled for this package.</p>

          <div class="mt-6">
            <h4 class="font-bold text-slate-700 dark:text-slate-200 mb-2">Current Redirects</h4>
            <ul v-if="redirects.length" class="job-list">
              <li v-for="r in redirects" :key="r.id" class="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-slate-200 dark:border-slate-700 flex justify-between items-center">
                <span><strong>{{ r.status_code }}</strong>: <code>{{ r.source_path }}</code> &rarr; <a :href="r.target_url" target="_blank" class="text-sky-600 underline">{{ r.target_url }}</a></span>
                <button type="button" class="cp-btn cp-btn-danger cp-btn-sm" @click="removeRedirect(r.id)">Remove</button>
        </li>
      </ul>
            <p v-else class="text-slate-500 text-sm italic">No redirects configured yet.</p>
          </div>
        </div>
      </div>
    </div>

    <!-- VIEW 5: ZONE EDITOR (DNS) -->
    <div v-else-if="currentView === 'dns'" class="cp-view-dns">
      <div class="cp-card">
        <div class="cp-card-header">
          <h2 class="cp-card-title">Zone Editor (DNS)</h2>
        </div>
        <div class="cp-card-body">
          <p class="muted">{{ zone?.message || 'Manage DNS records for this hosting domain.' }}</p>

          <form v-if="zone?.editable" class="form-row mt-4" @submit.prevent="addZone">
            <select v-model="zoneType" class="cp-text-input">
          <option>A</option>
          <option>AAAA</option>
          <option>CNAME</option>
          <option>MX</option>
          <option>TXT</option>
        </select>
            <input v-model="zoneHost" class="cp-text-input" placeholder="host (e.g. www, mail, @)" />
            <input v-model="zoneValue" class="cp-text-input grow" placeholder="record value" required />
            <button type="submit" class="cp-btn cp-btn-primary" :disabled="busy">Add Record</button>
      </form>

          <div class="mt-6">
            <h4 class="font-bold text-slate-700 dark:text-slate-200 mb-2">Active DNS Records</h4>
            <div class="cp-table-container">
              <table class="cp-domains-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Host</th>
                    <th>Points To / Value</th>
                    <th>TTL</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="rec in zone?.records || []" :key="rec.id">
                    <td><span class="badge-type">{{ rec.record_type }}</span></td>
                    <td class="font-mono text-sm">{{ rec.host }}</td>
                    <td class="font-mono text-sm break-all">{{ rec.value }}</td>
                    <td class="text-xs text-slate-500">{{ rec.ttl || 3600 }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- VIEW 6: GIT VERSION CONTROL -->
    <div v-else-if="currentView === 'git' && gitOn" class="cp-view-git">
      <div class="cp-card">
        <div class="cp-card-header">
          <h2 class="cp-card-title">Git™ Version Control</h2>
        </div>
        <div class="cp-card-body">
      <p class="muted">
        <template v-if="reposLimit === 1">This package includes 1 Git repository for this site.</template>
        <template v-else-if="reposLimit">This package includes up to {{ reposLimit }} Git repositories.</template>
            <template v-else>Clone a public repository into your site document root, then pull updates easily.</template>
      </p>

      <template v-if="git?.configured">
            <div class="p-4 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 mt-4">
              <p class="text-sm"><strong>Remote:</strong> <code>{{ git.remote }}</code></p>
              <p class="text-sm mt-1"><strong>Branch:</strong> <code>{{ git.branch }}</code></p>
              <p class="text-sm mt-1"><strong>Last Commit:</strong> <code>{{ git.commit }}</code></p>
              <button type="button" class="cp-btn cp-btn-primary mt-3" :disabled="busy" @click="pullGit">
                <i class="fas fa-code-branch mr-1" /> Pull Updates
              </button>
            </div>
      </template>

          <form v-else class="form-row mt-4" @submit.prevent="cloneGit">
            <input v-model="gitUrl" class="cp-text-input grow" placeholder="https://github.com/username/repository.git" required />
            <input v-model="gitBranch" class="cp-text-input" placeholder="main" />
            <button type="submit" class="cp-btn cp-btn-primary" :disabled="busy">Clone Repository</button>
      </form>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cp-domains-wrap {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: #333;
}
:root.dark .cp-domains-wrap {
  color: #e2e8f0;
}

/* Header & Breadcrumbs */
.cp-domains-header {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.cp-title-area {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.75rem;
}
.cp-page-title {
  font-size: 1.75rem;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
  letter-spacing: -0.02em;
}
:root.dark .cp-page-title {
  color: #f8fafc;
}
.cp-breadcrumbs {
  font-size: 0.88rem;
  color: #64748b;
  display: flex;
  gap: 0.35rem;
}
.crumb-link {
  color: #0284c7;
  text-decoration: none;
}
.crumb-link:hover {
  text-decoration: underline;
}
.crumb-sep {
  color: #94a3b8;
}
.crumb-current {
  color: #334155;
  font-weight: 500;
}
:root.dark .crumb-current {
  color: #cbd5e1;
}
.cp-doc-hint {
  font-size: 0.88rem;
  color: #475569;
  margin: 0;
}
:root.dark .cp-doc-hint {
  color: #94a3b8;
}
.cp-doc-link {
  color: #0284c7;
  text-decoration: underline;
}

/* Alert Notification */
.cp-alert {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  border-radius: 0.375rem;
  font-size: 0.88rem;
}
.cp-alert.ok {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
}
.cp-alert.err {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}
.cp-alert-close {
  margin-left: auto;
  background: transparent;
  border: none;
  font-size: 1.25rem;
  cursor: pointer;
  color: inherit;
}

/* Sub-nav Bar */
.cp-subnav-bar {
  display: flex;
  gap: 0.35rem;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 0.25rem;
  overflow-x: auto;
}
:root.dark .cp-subnav-bar {
  border-color: #334155;
}
.cp-subnav-btn {
  background: transparent;
  border: none;
  padding: 0.5rem 0.85rem;
  font-size: 0.86rem;
  font-weight: 500;
  color: #64748b;
  border-radius: 0.375rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  transition: all 0.15s ease;
}
.cp-subnav-btn:hover {
  background: #f1f5f9;
  color: #0f172a;
}
:root.dark .cp-subnav-btn:hover {
  background: #1e293b;
  color: #f8fafc;
}
.cp-subnav-btn.active {
  background: #0284c7;
  color: #fff;
}

/* Top Bar: Search and Count */
.cp-list-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.cp-search-box {
  display: flex;
  align-items: stretch;
  max-width: 280px;
  width: 100%;
}
.cp-search-input {
  flex: 1;
  border: 1px solid #cbd5e1;
  border-right: none;
  border-radius: 0.25rem 0 0 0.25rem;
  padding: 0.4rem 0.65rem;
  font-size: 0.86rem;
  background: #fff;
  color: #1e293b;
  outline: none;
}
:root.dark .cp-search-input {
  background: #1e293b;
  border-color: #475569;
  color: #f8fafc;
}
.cp-search-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 0 0.25rem 0.25rem 0;
  padding: 0 0.75rem;
  cursor: pointer;
  color: #64748b;
}
:root.dark .cp-search-btn {
  background: #334155;
  border-color: #475569;
  color: #cbd5e1;
}
.cp-display-count {
  font-size: 0.82rem;
  color: #64748b;
}

/* Action Toolbar */
.cp-toolbar-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 0.25rem;
}
.cp-toolbar-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
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
  text-decoration: none;
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
  border-color: #475569;
  color: #e2e8f0;
}
.cp-btn-default:hover:not(:disabled) {
  background: #f8fafc;
}
:root.dark .cp-btn-default:hover:not(:disabled) {
  background: #334155;
}
.cp-btn-danger {
  background: #dc2626;
  color: #fff;
}
.cp-btn-danger:hover:not(:disabled) {
  background: #b91c1c;
}
.cp-btn-action {
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #0284c7;
  font-size: 0.8rem;
  padding: 0.3rem 0.65rem;
  gap: 0.35rem;
}
:root.dark .cp-btn-action {
  background: #1e293b;
  border-color: #475569;
  color: #38bdf8;
}
.cp-btn-action:hover {
  background: #e0f2fe;
}
:root.dark .cp-btn-action:hover {
  background: #0369a1;
  color: #fff;
}
.cp-btn-sm {
  padding: 0.35rem 0.7rem;
  font-size: 0.82rem;
}
.cp-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* Data Table */
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
.cp-domains-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 0.86rem;
}
.cp-domains-table th {
  background: #f8fafc;
  color: #0284c7;
  font-weight: 600;
  padding: 0.65rem 0.85rem;
  border-bottom: 2px solid #cbd5e1;
  white-space: nowrap;
}
:root.dark .cp-domains-table th {
  background: #1e293b;
  border-color: #475569;
  color: #38bdf8;
}
.th-sortable {
  cursor: pointer;
  user-select: none;
}
.th-sortable:hover {
  background: #f1f5f9;
}
:root.dark .th-sortable:hover {
  background: #334155/60;
}
.th-content {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
}
.cp-sort-icon {
  font-size: 0.8rem;
  color: #94a3b8;
}
.cp-sort-icon.active {
  color: #0284c7;
}
:root.dark .cp-sort-icon.active {
  color: #38bdf8;
}
.cp-domains-table td {
  padding: 0.75rem 0.85rem;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}
:root.dark .cp-domains-table td {
  border-color: #1e293b;
}
.cp-domain-row:hover {
  background: #f8fafc;
}
:root.dark .cp-domain-row:hover {
  background: #1e293b/60;
}
.cp-domain-row.selected {
  background: #f0f9ff;
}
:root.dark .cp-domain-row.selected {
  background: #0369a1/20;
}
.th-check, .td-check {
  width: 38px;
  text-align: center;
}
.domain-name-cell {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.domain-link {
  color: #0284c7;
  font-weight: 500;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}
.domain-link:hover {
  text-decoration: underline;
}
.domain-ext-icon {
  font-size: 0.78rem;
  color: #0284c7;
}
.badge-primary-dom {
  font-size: 0.68rem;
  background: #e0f2fe;
  color: #0369a1;
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  font-weight: 600;
}
.docroot-link-btn {
  background: transparent;
  border: none;
  color: #0284c7;
  font-size: 0.86rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  padding: 0;
}
.docroot-link-btn:hover {
  text-decoration: underline;
}
.redirect-link {
  color: #0284c7;
  text-decoration: none;
}
.redirect-link:hover {
  text-decoration: underline;
}
.https-toggle-wrapper {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.cp-switch {
  width: 38px;
  height: 20px;
  background: #cbd5e1;
  border-radius: 999px;
  border: none;
  cursor: pointer;
  position: relative;
  transition: background 0.2s ease;
  padding: 2px;
}
.cp-switch.on {
  background: #0284c7;
}
.cp-switch-knob {
  display: block;
  width: 16px;
  height: 16px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.2s ease;
}
.cp-switch.on .cp-switch-knob {
  transform: translateX(18px);
}
.actions-btn-group {
  display: flex;
  gap: 0.35rem;
}

/* Cards & Forms */
.cp-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
:root.dark .cp-card {
  background: #0f172a;
  border-color: #334155;
}
.cp-card-header {
  padding: 0.85rem 1.25rem;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}
:root.dark .cp-card-header {
  background: #1e293b;
  border-color: #334155;
}
.cp-card-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: #1e293b;
}
:root.dark .cp-card-title {
  color: #f8fafc;
}
.cp-card-section-title {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #334155;
}
:root.dark .cp-card-section-title {
  color: #cbd5e1;
}
.cp-card-body {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.cp-form-group {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.cp-label-bold {
  font-weight: 600;
  font-size: 0.92rem;
  color: #1e293b;
}
:root.dark .cp-label-bold {
  color: #f1f5f9;
}
.cp-input-prompt {
  font-size: 0.86rem;
  color: #475569;
  margin: 0 0 0.25rem;
}
:root.dark .cp-input-prompt {
  color: #94a3b8;
}
.cp-text-input {
  border: 1px solid #cbd5e1;
  border-radius: 0.25rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.9rem;
  background: #fff;
  color: #1e293b;
  outline: none;
  max-width: 580px;
  width: 100%;
}
:root.dark .cp-text-input {
  background: #1e293b;
  border-color: #475569;
  color: #f8fafc;
}
.cp-text-input:focus {
  border-color: #0284c7;
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.2);
}
.cp-input-with-icon {
  display: flex;
  align-items: center;
  max-width: 580px;
  width: 100%;
}
.input-addon-icon {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-right: none;
  border-radius: 0.25rem 0 0 0.25rem;
  padding: 0.5rem 0.75rem;
  color: #64748b;
  display: flex;
  align-items: center;
}
:root.dark .input-addon-icon {
  background: #334155;
  border-color: #475569;
  color: #cbd5e1;
}
.cp-input-with-icon .cp-text-input {
  border-radius: 0 0.25rem 0.25rem 0;
}
.cp-help-icon {
  color: #0284c7;
  cursor: pointer;
  margin-left: 0.35rem;
  font-size: 0.88rem;
}
.cp-radio-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.cp-radio-option, .cp-checkbox-option {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  cursor: pointer;
}
.radio-desc-box, .checkbox-desc-box {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.radio-title, .checkbox-title {
  font-size: 0.88rem;
  color: #1e293b;
}
:root.dark .radio-title, :root.dark .checkbox-title {
  color: #f1f5f9;
}
.radio-sub, .checkbox-sub {
  font-size: 0.82rem;
  color: #64748b;
  margin: 0;
  line-height: 1.4;
}
.cp-package-banner {
  background: #fffbeb;
  border: 1px solid #fef3c7;
  border-radius: 0.375rem;
  padding: 0.75rem 1rem;
  display: flex;
  align-items: center;
  gap: 0.65rem;
  font-size: 0.86rem;
  color: #92400e;
}
:root.dark .cp-package-banner {
  background: #78350f/30;
  border-color: #78350f;
  color: #fde68a;
}
.cp-upgrade-link {
  color: #0284c7;
  font-weight: 600;
  text-decoration: underline;
  margin-left: 0.25rem;
}
.cp-form-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 0.5rem;
}
.cp-return-link {
  color: #0284c7;
  font-size: 0.88rem;
  text-decoration: none;
  margin-left: 0.5rem;
  display: inline-flex;
  align-items: center;
}
.cp-return-link:hover {
  text-decoration: underline;
}

/* Manage View Layout */
.cp-manage-title-wrap {
  margin-bottom: 0.25rem;
}
.cp-manage-heading {
  font-size: 1.5rem;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}
:root.dark .cp-manage-heading {
  color: #f8fafc;
}
.cp-manage-layout {
  display: grid;
  grid-template-columns: 2fr 1.2fr;
  gap: 1.5rem;
  align-items: start;
}
@media (max-width: 860px) {
  .cp-manage-layout {
    grid-template-columns: 1fr;
  }
}
.cp-manage-col-left {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.cp-danger-card {
  border: 1px solid #fecaca;
}
:root.dark .cp-danger-card {
  border-color: #7f1d1d;
}
.cp-danger-warning {
  font-size: 0.86rem;
  color: #475569;
  line-height: 1.5;
  margin: 0;
}
:root.dark .cp-danger-warning {
  color: #cbd5e1;
}

/* Sidebar in Manage View */
.cp-info-sidebar {
  border-left: 1px solid #e2e8f0;
  padding-left: 1.5rem;
}
:root.dark .cp-info-sidebar {
  border-color: #334155;
}
@media (max-width: 860px) {
  .cp-info-sidebar {
    border-left: none;
    border-top: 1px solid #e2e8f0;
    padding-left: 0;
    padding-top: 1.5rem;
  }
}
.cp-sidebar-title {
  font-size: 0.88rem;
  font-weight: 700;
  color: #334155;
  letter-spacing: 0.04em;
  margin: 0 0 1rem;
}
:root.dark .cp-sidebar-title {
  color: #cbd5e1;
}
.cp-info-dl {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  font-size: 0.86rem;
}
.info-row {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
}
.info-row dt {
  color: #64748b;
}
.info-row dd {
  margin: 0;
  color: #1e293b;
  text-align: right;
}
:root.dark .info-row dd {
  color: #f1f5f9;
}
.cp-sidebar-subtitle {
  font-size: 0.86rem;
  font-weight: 600;
  color: #334155;
  margin: 0 0 0.5rem;
}
:root.dark .cp-sidebar-subtitle {
  color: #cbd5e1;
}
.cp-resource-links {
  list-style: none;
  padding: 0;
  margin: 0;
  border: 1px solid #e2e8f0;
  border-radius: 0.25rem;
  background: #fff;
}
:root.dark .cp-resource-links {
  border-color: #334155;
  background: #0f172a;
}
.cp-resource-links li {
  border-bottom: 1px solid #f1f5f9;
}
:root.dark .cp-resource-links li {
  border-color: #1e293b;
}
.cp-resource-links li:last-child {
  border-bottom: none;
}
.resource-link {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.65rem 0.85rem;
  font-size: 0.84rem;
  color: #0284c7;
  text-decoration: none;
}
.resource-link:hover {
  background: #f8fafc;
  text-decoration: underline;
}
:root.dark .resource-link:hover {
  background: #1e293b;
}

/* Utilities */
.flex-center {
  display: flex;
  align-items: center;
}
.form-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}
.grow {
  flex: 1 1 14rem;
}
.badge-type {
  background: #e0f2fe;
  color: #0369a1;
  font-weight: 700;
  padding: 0.15rem 0.45rem;
  border-radius: 0.25rem;
  font-size: 0.76rem;
}
:root.dark .badge-type {
  background: #0369a1/30;
  color: #38bdf8;
}
.job-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.td-loading, .td-no-records {
  text-align: center;
  padding: 2.5rem 1rem !important;
  color: #64748b;
}
.muted {
  font-size: 0.86rem;
  color: #64748b;
  margin: 0;
}
</style>
