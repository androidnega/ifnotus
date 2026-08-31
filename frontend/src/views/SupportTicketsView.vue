<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { supportApi } from '@/api'
import type { SupportTicket } from '@/types/support'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import { playTicketRing15s, stopTicketRing, isSoundMuted, setSoundMuted } from '@/lib/sound'

const router = useRouter()
const { can } = usePermissions()
const canWrite = computed(() => can(Permission.SUPPORT_WRITE))

// State
const tickets = ref<SupportTicket[]>([])
const selected = ref<SupportTicket | null>(null)
const statusFilter = ref('')
const priorityFilter = ref('')
const searchQuery = ref('')
const loading = ref(true)
const error = ref('')
const reply = ref('')
const sendDirectMessage = ref(false)
const busy = ref(false)
const msg = ref('')
const copiedEmail = ref(false)
const copiedId = ref(false)
const copiedMessageId = ref<string | null>(null)

// Expanded message IDs for "Read More"
const expandedMessages = ref<Set<string>>(new Set())

// Sound alert state
const soundEnabled = ref(!isSoundMuted())
const isRinging = ref(false)
const ringingAlertText = ref('')
let pollTimer: number | null = null

// Track known message counts and ticket IDs to detect new incoming items
const knownMessageCounts = ref<Map<string, number>>(new Map())
const knownTicketIds = ref<Set<string>>(new Set())
const isInitialLoad = ref(true)

// Canned reply templates
const cannedReplies = [
  {
    label: '👋 Greeting & Investigating',
    text: 'Hello, thank you for reaching out to IFNOTUS Support. We have received your request and our engineering team is actively investigating. We will update you shortly.',
  },
  {
    label: '🌐 DNS Propagation Notice',
    text: 'Your DNS authoritative records have been provisioned and refreshed. Please allow 5 to 30 minutes for global DNS caching and resolver propagation to take effect.',
  },
  {
    label: '🔒 SSL / HTTPS Active',
    text: 'Your SSL/TLS certificate has been successfully validated and deployed to your web virtual host. Your domain is now secured with HTTPS.',
  },
  {
    label: '📁 File Permissions Restored',
    text: 'We have verified and corrected the file system permissions on your document root. Please try refreshing your browser or uploading your files again.',
  },
  {
    label: '❓ Need More Information',
    text: 'Could you please provide the exact error message or a screenshot of what you are seeing? Knowing the specific domain and URL path will help us resolve this faster.',
  },
  {
    label: '✅ Issue Resolved',
    text: 'The requested adjustments have been completed and verified on the server. Please test on your end and let us know if everything is working smoothly.',
  },
]

function toggleExpand(messageId: string) {
  if (expandedMessages.value.has(messageId)) {
    expandedMessages.value.delete(messageId)
  } else {
    expandedMessages.value.add(messageId)
  }
}

function isExpanded(messageId: string): boolean {
  return expandedMessages.value.has(messageId)
}

function isLongMessage(text: string): boolean {
  return (text || '').length > 280 || (text || '').split('\n').length > 5
}

function insertCanned(text: string) {
  if (reply.value.trim()) {
    reply.value += '\n\n' + text
  } else {
    reply.value = text
  }
}

function toggleSound() {
  soundEnabled.value = !soundEnabled.value
  setSoundMuted(!soundEnabled.value)
  if (!soundEnabled.value) {
    silenceRing()
  }
}

function triggerIncomingAlert(alertMessage: string) {
  if (!soundEnabled.value) return
  isRinging.value = true
  ringingAlertText.value = alertMessage

  playTicketRing15s(() => {
    isRinging.value = false
    ringingAlertText.value = ''
  })
}

function silenceRing() {
  stopTicketRing()
  isRinging.value = false
  ringingAlertText.value = ''
}

function apiErr(e: unknown, fallback: string) {
  const err = e as { response?: { data?: { error?: { message?: string } } } }
  return err.response?.data?.error?.message ?? fallback
}

// Counts for filter pills
const counts = computed(() => {
  const all = tickets.value.length
  const open = tickets.value.filter((t) => t.status === 'open').length
  const pending = tickets.value.filter((t) => t.status === 'pending').length
  const closed = tickets.value.filter((t) => t.status === 'closed').length
  const high = tickets.value.filter((t) => t.priority === 'high').length
  return { all, open, pending, closed, high }
})

// Filtered & Searched tickets
const filteredTickets = computed(() => {
  let list = tickets.value
  if (statusFilter.value) {
    list = list.filter((t) => t.status === statusFilter.value)
  }
  if (priorityFilter.value) {
    list = list.filter((t) => t.priority === priorityFilter.value)
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.toLowerCase().trim()
    list = list.filter(
      (t) =>
        t.subject?.toLowerCase().includes(q) ||
        t.customer_email?.toLowerCase().includes(q) ||
        t.customer_name?.toLowerCase().includes(q) ||
        t.id?.toLowerCase().includes(q),
    )
  }
  return list
})

async function loadList(isBackground = false) {
  if (!isBackground) loading.value = true
  error.value = ''
  try {
    const { data } = await supportApi.listTickets({
      status: statusFilter.value || undefined,
      priority: priorityFilter.value || undefined,
    })
    
    // Check for new tickets on background poll
    if (!isInitialLoad.value && isBackground) {
      const newItems = data.filter((t) => !knownTicketIds.value.has(t.id))
      if (newItems.length > 0) {
        const first = newItems[0]
        triggerIncomingAlert(`New Ticket: "${first.subject}" from ${first.customer_email || 'Customer'}`)
      }
    }

    tickets.value = data

    // Update known ticket set
    const currentIds = new Set<string>()
    data.forEach((t) => currentIds.add(t.id))
    knownTicketIds.value = currentIds

    // If a ticket is currently open, refresh its conversation in background
    if (selected.value) {
      await refreshCurrentTicket(isBackground)
    }
  } catch (e: unknown) {
    if (!isBackground) {
      error.value = apiErr(e, 'Could not load tickets.')
    }
  } finally {
    if (!isBackground) loading.value = false
    isInitialLoad.value = false
  }
}

async function refreshCurrentTicket(isBackground = false) {
  if (!selected.value) return
  try {
    const { data } = await supportApi.getTicket(selected.value.id)
    const prevCount = knownMessageCounts.value.get(selected.value.id) ?? 0
    const currentCount = data.messages?.length ?? 0

    if (!isInitialLoad.value && currentCount > prevCount && isBackground) {
      const latestMsg = data.messages?.[data.messages.length - 1]
      if (latestMsg && latestMsg.author_role !== 'staff') {
        triggerIncomingAlert(`New message in "${data.subject}" from ${data.customer_email || 'Customer'}`)
      }
    }

    selected.value = data
    knownMessageCounts.value.set(selected.value.id, currentCount)
  } catch {
    /* ignore background refresh error */
  }
}

async function openTicket(id: string) {
  msg.value = ''
  silenceRing()
  try {
    const { data } = await supportApi.getTicket(id)
    selected.value = data
    knownMessageCounts.value.set(id, data.messages?.length ?? 0)
    await nextTick()
    scrollThreadToBottom()
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not open ticket.')
  }
}

function scrollThreadToBottom() {
  const container = document.getElementById('ticket-chat-scroll')
  if (container) {
    container.scrollTop = container.scrollHeight
  }
}

async function sendReply() {
  if (!selected.value || !reply.value.trim() || !canWrite.value) return
  busy.value = true
  msg.value = ''
  try {
    await supportApi.replyTicket(selected.value.id, reply.value.trim(), sendDirectMessage.value)
    reply.value = ''
    sendDirectMessage.value = false
    await openTicket(selected.value.id)
    await loadList(true)
    msg.value = 'Reply sent successfully.'
    setTimeout(() => {
      if (msg.value === 'Reply sent successfully.') msg.value = ''
    }, 4000)
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Reply failed.')
  } finally {
    busy.value = false
  }
}

function handleKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    void sendReply()
  }
}

async function closeTicket() {
  if (!selected.value || !canWrite.value) return
  busy.value = true
  try {
    await supportApi.closeTicket(selected.value.id)
    await openTicket(selected.value.id)
    await loadList(true)
    msg.value = 'Ticket closed.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Close failed.')
  } finally {
    busy.value = false
  }
}

async function reopenTicket() {
  if (!selected.value || !canWrite.value) return
  busy.value = true
  try {
    await supportApi.reopenTicket(selected.value.id)
    await openTicket(selected.value.id)
    await loadList(true)
    msg.value = 'Ticket reopened.'
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Reopen failed.')
  } finally {
    busy.value = false
  }
}

async function changePriority(priority: string) {
  if (!selected.value || !canWrite.value) return
  busy.value = true
  try {
    await supportApi.setTicketPriority(selected.value.id, priority)
    await openTicket(selected.value.id)
    await loadList(true)
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not update priority.')
  } finally {
    busy.value = false
  }
}

function openCustomer() {
  if (!selected.value?.customer_id) return
  router.push({ name: 'platform-customers', query: { open: selected.value.customer_id } })
}

function copyCustomerEmail() {
  if (!selected.value?.customer_email) return
  navigator.clipboard.writeText(selected.value.customer_email)
  copiedEmail.value = true
  setTimeout(() => {
    copiedEmail.value = false
  }, 2000)
}

function copyTicketId() {
  if (!selected.value?.id) return
  navigator.clipboard.writeText(selected.value.id)
  copiedId.value = true
  setTimeout(() => {
    copiedId.value = false
  }, 2000)
}

function copyMessage(text: string, id: string) {
  navigator.clipboard.writeText(text)
  copiedMessageId.value = id
  setTimeout(() => {
    if (copiedMessageId.value === id) copiedMessageId.value = null
  }, 2000)
}

function formatRelativeTime(dateStr?: string | null): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000)
  if (diffSec < 30) return 'Just now'
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHours = Math.floor(diffMin / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function formatExactDate(dateStr?: string | null): string {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

onMounted(() => {
  void loadList()
  // Background polling every 10 seconds for real-time ticket desk updates and sound alert
  pollTimer = window.setInterval(() => {
    void loadList(true)
  }, 10000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  silenceRing()
})

watch([statusFilter, priorityFilter], () => {
  void loadList()
})
</script>

<template>
  <DashboardLayout>
    <div class="space-y-4 p-4 md:p-6 max-w-7xl mx-auto">
      <!-- Top Ringing Notification Banner -->
      <transition name="slide-down">
        <div
          v-if="isRinging"
          class="relative flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-400/80 bg-gradient-to-r from-amber-500 via-orange-500 to-amber-600 px-4 py-3 text-white shadow-lg animate-pulse"
        >
          <div class="flex items-center gap-3">
            <span class="flex h-9 w-9 items-center justify-center rounded-full bg-white/20 text-lg shadow-inner">
              🔔
            </span>
            <div>
              <p class="font-bold tracking-wide text-sm md:text-base">
                Incoming Ticket Ring Alert (Ringing for 15s)
              </p>
              <p class="text-xs text-amber-100">{{ ringingAlertText || 'New support message received!' }}</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-slate-900 shadow hover:bg-amber-50 transition active:scale-95"
              @click="silenceRing"
            >
              🔇 Silence Ring
            </button>
          </div>
        </div>
      </transition>

      <!-- Header -->
      <UiPageHeader
        title="Support Desk"
        lede="Triage customer requests, provide live resolutions, and monitor incoming tickets in real-time."
      >
        <template #actions>
          <div class="flex flex-wrap items-center gap-2">
            <!-- Sound toggle -->
            <button
              type="button"
              class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition"
              :class="
                soundEnabled
                  ? 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-700/60 dark:bg-emerald-950/40 dark:text-emerald-300'
                  : 'border-slate-300 bg-slate-100 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400'
              "
              :title="soundEnabled ? 'Ring sound alert is active (15s on new message). Click to mute.' : 'Sound alert is muted. Click to enable.'"
              @click="toggleSound"
            >
              <span>{{ soundEnabled ? '🔔 15s Ring On' : '🔕 Muted' }}</span>
            </button>

            <!-- Refresh button -->
            <button
              type="button"
              class="flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 transition"
              :disabled="loading"
              @click="loadList(false)"
            >
              <span :class="{ 'animate-spin': loading }">🔄</span>
              <span>Refresh</span>
            </button>
          </div>
        </template>
      </UiPageHeader>

      <p v-if="loading && !tickets.length" class="text-sm text-slate-500 dark:text-slate-400 py-8 text-center">
        Loading support queue…
      </p>
      <UiAlert v-else-if="error" tone="err">{{ error }}</UiAlert>

      <!-- Main Layout: 2 Columns on Desktop -->
      <div v-else class="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        <!-- Left: Ticket Queue List (5 cols) -->
        <div
          class="lg:col-span-5 flex flex-col rounded-2xl border border-slate-200/90 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 overflow-hidden"
        >
          <!-- Search & Filter Controls -->
          <div class="p-3.5 border-b border-slate-100 dark:border-slate-800 space-y-2.5 bg-slate-50/70 dark:bg-slate-900/60">
            <!-- Search Bar -->
            <div class="relative">
              <input
                v-model="searchQuery"
                type="text"
                placeholder="Search by subject, email, or ticket ID…"
                class="w-full rounded-xl border border-slate-200 bg-white pl-9 pr-3 py-1.5 text-xs text-slate-800 placeholder-slate-400 focus:border-slate-400 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:placeholder-slate-500"
              />
              <span class="absolute left-3 top-2 text-slate-400 text-xs">🔍</span>
              <button
                v-if="searchQuery"
                type="button"
                class="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 text-xs"
                @click="searchQuery = ''"
              >
                ✕
              </button>
            </div>

            <!-- Status Tabs & Priority Filter -->
            <div class="flex flex-wrap items-center justify-between gap-1.5 text-xs">
              <div class="flex flex-wrap items-center gap-1">
                <button
                  type="button"
                  class="rounded-lg px-2.5 py-1 text-xs font-medium transition"
                  :class="
                    statusFilter === ''
                      ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                      : 'text-slate-600 hover:bg-slate-200/70 dark:text-slate-400 dark:hover:bg-slate-800'
                  "
                  @click="statusFilter = ''"
                >
                  All ({{ counts.all }})
                </button>
                <button
                  type="button"
                  class="rounded-lg px-2.5 py-1 text-xs font-medium transition"
                  :class="
                    statusFilter === 'open'
                      ? 'bg-emerald-600 text-white'
                      : 'text-emerald-700 hover:bg-emerald-100/60 dark:text-emerald-400 dark:hover:bg-emerald-950/40'
                  "
                  @click="statusFilter = 'open'"
                >
                  Open ({{ counts.open }})
                </button>
                <button
                  type="button"
                  class="rounded-lg px-2.5 py-1 text-xs font-medium transition"
                  :class="
                    statusFilter === 'pending'
                      ? 'bg-amber-600 text-white'
                      : 'text-amber-700 hover:bg-amber-100/60 dark:text-amber-400 dark:hover:bg-amber-950/40'
                  "
                  @click="statusFilter = 'pending'"
                >
                  Pending ({{ counts.pending }})
                </button>
                <button
                  type="button"
                  class="rounded-lg px-2.5 py-1 text-xs font-medium transition"
                  :class="
                    statusFilter === 'closed'
                      ? 'bg-slate-600 text-white dark:bg-slate-600'
                      : 'text-slate-600 hover:bg-slate-200/70 dark:text-slate-400 dark:hover:bg-slate-800'
                  "
                  @click="statusFilter = 'closed'"
                >
                  Closed ({{ counts.closed }})
                </button>
              </div>

              <!-- Priority Dropdown -->
              <select
                v-model="priorityFilter"
                class="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                <option value="">Priority: All</option>
                <option value="high">🔴 High</option>
                <option value="normal">🟡 Normal</option>
                <option value="low">🔵 Low</option>
              </select>
            </div>
          </div>

          <!-- Ticket List Items -->
          <div class="max-h-[38rem] overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800">
            <button
              v-for="t in filteredTickets"
              :key="t.id"
              type="button"
              class="w-full text-left p-3.5 transition flex flex-col gap-1.5 focus:outline-none"
              :class="[
                selected?.id === t.id
                  ? 'bg-amber-50/80 border-l-4 border-amber-500 dark:bg-amber-950/30 dark:border-amber-400'
                  : 'hover:bg-slate-50/80 dark:hover:bg-slate-800/60',
              ]"
              @click="openTicket(t.id)"
            >
              <div class="flex items-start justify-between gap-2">
                <span class="font-semibold text-xs md:text-sm text-slate-900 dark:text-slate-100 line-clamp-1">
                  {{ t.subject }}
                </span>
                <span class="shrink-0 text-[11px] font-medium text-slate-400">
                  {{ formatRelativeTime(t.updated_at || t.created_at) }}
                </span>
              </div>

              <div class="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <span class="truncate max-w-[200px] text-slate-600 dark:text-slate-300">
                  {{ t.customer_name || t.customer_email || t.customer_id }}
                </span>
                <div class="flex items-center gap-1.5 shrink-0">
                  <!-- Priority badge -->
                  <span
                    class="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider"
                    :class="{
                      'bg-rose-100 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300': t.priority === 'high',
                      'bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300': t.priority === 'normal',
                      'bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300': t.priority === 'low',
                    }"
                  >
                    {{ t.priority }}
                  </span>
                  <!-- Status badge -->
                  <span
                    class="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider"
                    :class="{
                      'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300': t.status === 'open',
                      'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300': t.status === 'pending',
                      'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400': t.status === 'closed',
                    }"
                  >
                    {{ t.status }}
                  </span>
                </div>
              </div>
            </button>

            <!-- Empty state in queue -->
            <div v-if="!filteredTickets.length" class="p-8 text-center text-sm text-slate-400">
              <span class="text-2xl block mb-1">📭</span>
              No tickets found in this view.
            </div>
          </div>
        </div>

        <!-- Right: Active Ticket Conversation & Agent Actions (7 cols) -->
        <div
          class="lg:col-span-7 flex flex-col rounded-2xl border border-slate-200/90 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 overflow-hidden"
        >
          <!-- When No Ticket Selected -->
          <div v-if="!selected" class="p-12 text-center text-slate-400 space-y-3">
            <span class="text-4xl block">💬</span>
            <p class="font-medium text-slate-700 dark:text-slate-300">No ticket selected</p>
            <p class="text-xs text-slate-500 max-w-sm mx-auto">
              Select a ticket from the queue on the left to view messages, update priority, or send a reply.
            </p>
          </div>

          <!-- Active Ticket Details -->
          <template v-else>
            <!-- Ticket Header & Quick Info -->
            <div class="p-4 border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50 space-y-3">
              <!-- Top Row: Subject & Action Buttons -->
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="space-y-1">
                  <h3 class="font-bold text-base md:text-lg text-slate-900 dark:text-slate-100 leading-snug">
                    {{ selected.subject }}
                  </h3>
                  <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                    <span class="font-semibold text-slate-800 dark:text-slate-200">
                      {{ selected.customer_name || 'Customer' }}
                    </span>
                    <span>·</span>
                    <button
                      type="button"
                      class="hover:text-slate-900 dark:hover:text-slate-100 underline decoration-dotted"
                      :title="'Copy ' + (selected.customer_email || '')"
                      @click="copyCustomerEmail"
                    >
                      {{ selected.customer_email || 'No email' }}
                      <span v-if="copiedEmail" class="text-emerald-600 font-bold ml-1">✓ Copied!</span>
                    </button>
                    <span>·</span>
                    <button
                      type="button"
                      class="font-mono text-[11px] text-slate-400 hover:text-slate-600"
                      title="Copy Ticket ID"
                      @click="copyTicketId"
                    >
                      #{{ selected.id.slice(0, 8) }}
                      <span v-if="copiedId" class="text-emerald-600 font-bold ml-1">✓</span>
                    </button>
                  </div>
                </div>

                <!-- Action buttons -->
                <div class="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    class="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 transition"
                    @click="openCustomer"
                  >
                    👤 Open Customer
                  </button>
                  <button
                    v-if="canWrite && selected.status !== 'closed'"
                    type="button"
                    class="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 transition"
                    :disabled="busy"
                    @click="closeTicket"
                  >
                    ✓ Close Ticket
                  </button>
                  <button
                    v-if="canWrite && selected.status === 'closed'"
                    type="button"
                    class="rounded-lg border border-emerald-300 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800 shadow-sm hover:bg-emerald-100 dark:border-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300 transition"
                    :disabled="busy"
                    @click="reopenTicket"
                  >
                    ↺ Reopen Ticket
                  </button>
                </div>
              </div>

              <!-- Second Row: Priority, Status, and Controls -->
              <div class="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-slate-200/60 dark:border-slate-800/60 text-xs">
                <div class="flex items-center gap-2">
                  <span class="text-slate-400 font-medium">Priority:</span>
                  <select
                    class="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-800 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                    :value="selected.priority"
                    :disabled="busy || !canWrite"
                    @change="changePriority(($event.target as HTMLSelectElement).value)"
                  >
                    <option value="low">🔵 Low Priority</option>
                    <option value="normal">🟡 Normal Priority</option>
                    <option value="high">🔴 High Priority</option>
                  </select>
                </div>

                <div class="flex items-center gap-2 text-slate-400">
                  <span>Created: {{ formatExactDate(selected.created_at) }}</span>
                </div>
              </div>
            </div>

            <!-- Feedback Message Banner -->
            <div
              v-if="msg"
              class="mx-4 mt-3 rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs font-medium text-emerald-800 dark:bg-emerald-950/40 dark:border-emerald-800 dark:text-emerald-300"
            >
              {{ msg }}
            </div>

            <!-- Messages Thread View -->
            <div
              id="ticket-chat-scroll"
              class="p-4 space-y-4 max-h-[26rem] overflow-y-auto bg-slate-50/30 dark:bg-slate-900/30"
            >
              <div
                v-for="m in selected.messages || []"
                :key="m.id"
                class="flex flex-col gap-1.5 transition"
                :class="m.author_role === 'staff' ? 'items-end' : 'items-start'"
              >
                <!-- Role & Time header -->
                <div class="flex items-center gap-2 px-1 text-[11px] text-slate-400">
                  <span class="font-semibold" :class="m.author_role === 'staff' ? 'text-amber-600 dark:text-amber-400' : 'text-sky-600 dark:text-sky-400'">
                    {{ m.author_role === 'staff' ? '🛡️ Support Specialist (Staff)' : '👤 Customer' }}
                  </span>
                  <span>·</span>
                  <span :title="formatExactDate(m.created_at)">
                    {{ formatRelativeTime(m.created_at) }}
                  </span>
                </div>

                <!-- Chat Bubble Container -->
                <div
                  class="relative max-w-[90%] md:max-w-[80%] rounded-2xl p-4 shadow-sm text-xs md:text-sm leading-relaxed"
                  :class="[
                    m.author_role === 'staff'
                      ? 'bg-slate-900 text-white rounded-tr-none dark:bg-amber-950/40 dark:text-slate-100 dark:border dark:border-amber-800/40'
                      : 'bg-white text-slate-800 border border-slate-200/80 rounded-tl-none dark:bg-slate-800 dark:text-slate-100 dark:border-slate-700',
                  ]"
                >
                  <!-- Message Text with Read More / Show Less Wrap -->
                  <div
                    class="whitespace-pre-wrap break-words"
                    :class="{
                      'line-clamp-5 overflow-hidden': isLongMessage(m.body) && !isExpanded(m.id),
                    }"
                  >
                    {{ m.body }}
                  </div>

                  <!-- Read More / Show Less Button if long -->
                  <div v-if="isLongMessage(m.body)" class="mt-2 pt-2 border-t border-slate-700/40 dark:border-slate-700/60">
                    <button
                      type="button"
                      class="text-xs font-semibold underline decoration-dotted transition"
                      :class="m.author_role === 'staff' ? 'text-amber-300 hover:text-amber-200' : 'text-sky-600 hover:text-sky-700 dark:text-sky-400'"
                      @click="toggleExpand(m.id)"
                    >
                      {{ isExpanded(m.id) ? '▲ Show less' : '▼ Read full message' }}
                    </button>
                  </div>

                  <!-- Quick Copy Button on hover -->
                  <button
                    type="button"
                    class="absolute top-2 right-2 text-[10px] opacity-40 hover:opacity-100 transition rounded px-1.5 py-0.5 bg-black/10 dark:bg-white/10"
                    title="Copy message text"
                    @click="copyMessage(m.body, m.id)"
                  >
                    {{ copiedMessageId === m.id ? '✓' : 'Copy' }}
                  </button>
                </div>
              </div>

              <!-- Empty message thread -->
              <div v-if="!selected.messages?.length" class="text-center py-8 text-xs text-slate-400">
                No messages recorded in this ticket thread yet.
              </div>
            </div>

            <!-- Agent Reply Box & Canned Responses -->
            <div v-if="canWrite" class="p-4 border-t border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 space-y-3">
              <!-- Quick Response Templates Chips -->
              <div class="space-y-1.5">
                <div class="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                  <span class="font-medium text-[11px] uppercase tracking-wider">⚡ Quick Responses:</span>
                  <span class="text-[11px] text-slate-400">Click chip to insert template</span>
                </div>
                <div class="flex flex-wrap gap-1.5">
                  <button
                    v-for="cr in cannedReplies"
                    :key="cr.label"
                    type="button"
                    class="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-700 hover:bg-amber-50 hover:border-amber-300 hover:text-amber-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-amber-950/40 dark:hover:text-amber-300 transition"
                    @click="insertCanned(cr.text)"
                  >
                    {{ cr.label }}
                  </button>
                </div>
              </div>

              <!-- Reply Form -->
              <form class="space-y-2.5" @submit.prevent="sendReply">
                <div class="relative">
                  <textarea
                    v-model="reply"
                    rows="3"
                    class="w-full rounded-xl border border-slate-300 bg-slate-50/50 p-3 text-xs md:text-sm text-slate-900 placeholder-slate-400 focus:border-slate-500 focus:bg-white focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:placeholder-slate-500 dark:focus:bg-slate-900"
                    :placeholder="
                      selected.status === 'closed'
                        ? 'Ticket is currently closed. Sending a reply will automatically reopen this ticket…'
                        : 'Type your response to the customer… (Press Ctrl+Enter to send)'
                    "
                    @keydown="handleKeydown"
                  />
                  <span class="absolute right-3 bottom-3 text-[10px] text-slate-400">
                    {{ reply.length }} chars
                  </span>
                </div>

                <div class="flex flex-wrap items-center justify-between gap-2">
                  <label class="inline-flex items-center gap-2 cursor-pointer select-none text-xs text-slate-700 dark:text-slate-300 font-medium hover:text-slate-900 dark:hover:text-white bg-slate-100/80 dark:bg-slate-800/80 px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700">
                    <input
                      v-model="sendDirectMessage"
                      type="checkbox"
                      class="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-700"
                    />
                    <span class="inline-flex items-center gap-1.5">
                      <i class="fa-solid fa-paper-plane text-indigo-500" />
                      <span>Send direct SMS &amp; alert notification to customer phone</span>
                    </span>
                  </label>

                  <div class="flex items-center gap-3">
                    <p class="text-[11px] text-slate-400 hidden sm:block">
                      Shortcut: <kbd class="px-1.5 py-0.5 rounded border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-[10px] font-mono">Ctrl</kbd> + <kbd class="px-1.5 py-0.5 rounded border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-[10px] font-mono">Enter</kbd>
                    </p>
                    <button
                      type="submit"
                      class="flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-xs md:text-sm font-semibold text-white shadow hover:bg-slate-800 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white transition"
                      :disabled="busy || !reply.trim()"
                    >
                      <span v-if="busy" class="animate-spin">⌛</span>
                      <span>{{ selected.status === 'closed' ? 'Reopen & Send Reply' : 'Send Support Reply' }}</span>
                    </button>
                  </div>
                </div>
              </form>
            </div>
          </template>
        </div>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
}
.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
