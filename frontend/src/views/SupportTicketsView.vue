<script setup lang="ts">
import { onMounted, computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { supportApi } from '@/api'
import type { SupportTicket } from '@/types/support'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'

const router = useRouter()
const { can } = usePermissions()
const canWrite = computed(() => can(Permission.SUPPORT_WRITE))

const tickets = ref<SupportTicket[]>([])
const selected = ref<SupportTicket | null>(null)
const statusFilter = ref('')
const priorityFilter = ref('')
const loading = ref(true)
const error = ref('')
const reply = ref('')
const busy = ref(false)
const msg = ref('')

function apiErr(e: unknown, fallback: string) {
  const err = e as { response?: { data?: { error?: { message?: string } } } }
  return err.response?.data?.error?.message ?? fallback
}

async function loadList() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await supportApi.listTickets({
      status: statusFilter.value || undefined,
      priority: priorityFilter.value || undefined,
    })
    tickets.value = data
  } catch (e: unknown) {
    error.value = apiErr(e, 'Could not load tickets.')
  } finally {
    loading.value = false
  }
}

async function openTicket(id: string) {
  msg.value = ''
  try {
    const { data } = await supportApi.getTicket(id)
    selected.value = data
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Could not open ticket.')
  }
}

async function sendReply() {
  if (!selected.value || !reply.value.trim() || !canWrite.value) return
  busy.value = true
  try {
    await supportApi.replyTicket(selected.value.id, reply.value.trim())
    reply.value = ''
    await openTicket(selected.value.id)
    await loadList()
  } catch (e: unknown) {
    msg.value = apiErr(e, 'Reply failed.')
  } finally {
    busy.value = false
  }
}

async function closeTicket() {
  if (!selected.value || !canWrite.value) return
  busy.value = true
  try {
    await supportApi.closeTicket(selected.value.id)
    await openTicket(selected.value.id)
    await loadList()
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
    await loadList()
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
    await loadList()
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

onMounted(loadList)
watch([statusFilter, priorityFilter], loadList)
</script>

<template>
  <DashboardLayout>
    <div class="space-y-4 p-6">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold">Support tickets</h1>
          <p class="text-sm text-slate-500">Helpdesk queue — reply, reopen, set priority, jump to customer</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <select
            v-model="statusFilter"
            class="rounded border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900"
          >
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="pending">Pending</option>
            <option value="closed">Closed</option>
          </select>
          <select
            v-model="priorityFilter"
            class="rounded border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900"
          >
            <option value="">All priorities</option>
            <option value="low">Low</option>
            <option value="normal">Normal</option>
            <option value="high">High</option>
          </select>
          <button type="button" class="rounded border border-slate-300 px-3 py-1.5 text-sm" @click="loadList">
            Refresh
          </button>
        </div>
      </div>

      <p v-if="loading" class="text-sm text-slate-500">Loading…</p>
      <p v-else-if="error" class="text-sm text-red-600">{{ error }}</p>

      <div v-else class="grid gap-4 lg:grid-cols-2">
        <div class="rounded border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
          <ul class="divide-y divide-slate-100 dark:divide-slate-800">
            <li v-for="t in tickets" :key="t.id">
              <button
                type="button"
                class="flex w-full flex-col gap-0.5 px-4 py-3 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
                @click="openTicket(t.id)"
              >
                <span class="font-medium">{{ t.subject }}</span>
                <span class="text-xs text-slate-500">
                  {{ t.status }} · {{ t.priority }} · {{ t.customer_email || t.customer_id }}
                </span>
              </button>
            </li>
            <li v-if="!tickets.length" class="px-4 py-6 text-sm text-slate-500">No tickets.</li>
          </ul>
        </div>

        <div class="rounded border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
          <p v-if="msg" class="mb-2 text-sm text-slate-600">{{ msg }}</p>
          <p v-if="!selected" class="text-sm text-slate-500">Select a ticket.</p>
          <template v-else>
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p class="font-medium">{{ selected.subject }}</p>
                <p class="text-xs text-slate-500">
                  {{ selected.customer_name || 'Customer' }} · {{ selected.customer_email }} ·
                  {{ selected.status }} · {{ selected.priority }}
                </p>
              </div>
              <div class="flex flex-wrap gap-1">
                <button
                  type="button"
                  class="rounded border border-slate-300 px-2 py-1 text-xs"
                  @click="openCustomer"
                >
                  Open customer
                </button>
                <button
                  v-if="canWrite && selected.status !== 'closed'"
                  type="button"
                  class="rounded border border-slate-300 px-2 py-1 text-xs"
                  :disabled="busy"
                  @click="closeTicket"
                >
                  Close
                </button>
                <button
                  v-if="canWrite && selected.status === 'closed'"
                  type="button"
                  class="rounded border border-emerald-400 px-2 py-1 text-xs text-emerald-800"
                  :disabled="busy"
                  @click="reopenTicket"
                >
                  Reopen
                </button>
              </div>
            </div>

            <div v-if="canWrite" class="mt-2 flex items-center gap-2 text-xs">
              <span class="text-slate-500">Priority</span>
              <select
                class="rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                :value="selected.priority"
                :disabled="busy"
                @change="changePriority(($event.target as HTMLSelectElement).value)"
              >
                <option value="low">Low</option>
                <option value="normal">Normal</option>
                <option value="high">High</option>
              </select>
            </div>

            <div class="mt-4 max-h-[28rem] space-y-3 overflow-y-auto">
              <div
                v-for="m in selected.messages || []"
                :key="m.id"
                class="rounded px-3 py-2 text-sm"
                :class="m.author_role === 'staff' ? 'bg-amber-50 dark:bg-amber-950/30' : 'bg-slate-50 dark:bg-slate-800'"
              >
                <p class="text-[11px] uppercase text-slate-500">{{ m.author_role }}</p>
                <p class="mt-1 whitespace-pre-wrap">{{ m.body }}</p>
              </div>
            </div>
            <form
              v-if="canWrite"
              class="mt-4 space-y-2"
              @submit.prevent="sendReply"
            >
              <textarea
                v-model="reply"
                rows="3"
                class="w-full rounded border border-slate-300 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900"
                :placeholder="selected.status === 'closed' ? 'Reply will reopen this ticket…' : 'Staff reply…'"
              />
              <button
                type="submit"
                class="rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-white dark:text-slate-900"
                :disabled="busy || !reply.trim()"
              >
                {{ selected.status === 'closed' ? 'Reply & reopen' : 'Send reply' }}
              </button>
            </form>
          </template>
        </div>
      </div>
    </div>
  </DashboardLayout>
</template>
