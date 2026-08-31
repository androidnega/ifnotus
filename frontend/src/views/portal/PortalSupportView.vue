<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { catalogApi, customersApi } from '@/api'
import PortalAccountNav from '@/components/portal/PortalAccountNav.vue'
import PortalShell from '@/components/portal/PortalShell.vue'
import PortalFeatureCard from '@/components/portal/PortalFeatureCard.vue'
import { IconMail, IconShield } from '@/components/icons'
import { planAccentFromPrice } from '@/lib/theme'
import { useSiteTheme } from '@/composables/useSiteTheme'
import { getApiErrorMessage } from '@/lib/apiError'
import type { SupportTicket } from '@/types/support'
import type { HostingPlan } from '@/types/platform'

defineProps<{ embed?: boolean }>()

const { planColors, load: loadTheme } = useSiteTheme()
const tickets = ref<SupportTicket[]>([])
const selected = ref<SupportTicket | null>(null)
const loading = ref(true)
const error = ref('')
const department = ref('Technical Support')
const subject = ref('')
const body = ref('')
const priority = ref('normal')
const reply = ref('')
const busy = ref(false)
const msg = ref('')
const planAccent = ref('#1e3a5f')
const expandedMessages = ref<Set<string>>(new Set())
const copiedMsgId = ref<string | null>(null)

const activeOpenTicket = computed(() =>
  tickets.value.find((t) => ['open', 'pending', 'in_progress'].includes((t.status || '').toLowerCase())),
)

function toggleExpand(id: string) {
  if (expandedMessages.value.has(id)) {
    expandedMessages.value.delete(id)
  } else {
    expandedMessages.value.add(id)
  }
}

function isExpanded(id: string): boolean {
  return expandedMessages.value.has(id)
}

function isLong(text: string): boolean {
  return (text || '').length > 280 || (text || '').split('\n').length > 5
}

function copyText(text: string, id: string) {
  navigator.clipboard.writeText(text)
  copiedMsgId.value = id
  setTimeout(() => {
    if (copiedMsgId.value === id) copiedMsgId.value = null
  }, 2000)
}

function formatTime(dateStr?: string | null): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

async function loadList() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await customersApi.listTickets()
    tickets.value = data
  } catch (e: unknown) {
    error.value = getApiErrorMessage(e, 'Could not load tickets.')
  } finally {
    loading.value = false
  }
}

async function openTicket(id: string) {
  msg.value = ''
  try {
    const { data } = await customersApi.getTicket(id)
    selected.value = data
    if (!selected.value.messages?.length) {
      selected.value = { ...data, messages: data.messages || [] }
    }
  } catch (e: unknown) {
    msg.value = getApiErrorMessage(e, 'Could not open ticket.')
  }
}

async function createTicket() {
  if (!subject.value.trim() || !body.value.trim()) return
  if (activeOpenTicket.value) {
    msg.value = 'You already have an active support ticket. Please reply to your existing ticket.'
    return
  }
  busy.value = true
  msg.value = ''
  try {
    const { data } = await customersApi.createTicket({
      department: department.value,
      subject: subject.value.trim(),
      body: body.value.trim(),
      priority: priority.value,
    })
    subject.value = ''
    body.value = ''
    priority.value = 'normal'
    department.value = 'Technical Support'
    await loadList()
    if (data?.id) await openTicket(data.id)
    else selected.value = data
    msg.value = 'Ticket created. IFNOTUS staff will reply in this thread.'
  } catch (e: unknown) {
    msg.value = getApiErrorMessage(e, 'Create failed.')
  } finally {
    busy.value = false
  }
}

async function sendReply() {
  if (!selected.value || !reply.value.trim()) return
  busy.value = true
  msg.value = ''
  try {
    await customersApi.replyTicket(selected.value.id, reply.value.trim())
    reply.value = ''
    await openTicket(selected.value.id)
    await loadList()
  } catch (e: unknown) {
    msg.value = getApiErrorMessage(e, 'Reply failed.')
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  await loadTheme()
  try {
    const [dash, plans] = await Promise.all([customersApi.dashboard(), catalogApi.plans()])
    const sub = dash.data.subscriptions[0]
    const plan = (plans.data.items as HostingPlan[]).find((p) => p.id === sub?.plan_id)
    if (plan) {
      planAccent.value = planAccentFromPrice(Number(plan.price_monthly), planColors.value, plan.features)
    }
  } catch {
    /* keep default accent */
  }
  await loadList()
})
</script>

<template>
  <PortalShell v-if="!embed" mode="app" :plan-accent="planAccent" profile-menu>
    <template #sidebar>
      <PortalAccountNav active="support" />
    </template>
    <div class="support-body">
      <div class="head">
        <p class="p-kicker">Help</p>
        <h1>Support</h1>
        <p class="lede">DNS, SSL, files, billing — replies stay in your private ticket thread.</p>
      </div>

      <div class="p-banner mb">
        <strong>Account-scoped.</strong>
        Tickets stay on this account. IFNOTUS staff reply in the same thread.
      </div>

      <div class="hint-grid mb">
        <PortalFeatureCard title="Fast triage" description="Include your domain and what changed last.">
          <template #icon><IconMail :size="18" /></template>
        </PortalFeatureCard>
        <PortalFeatureCard title="Private thread" description="Conversation history stays on this account.">
          <template #icon><IconShield :size="18" /></template>
        </PortalFeatureCard>
      </div>

      <div class="grid">
        <section class="stack">
          <div class="p-card">
            <h2>New ticket</h2>
            <div v-if="activeOpenTicket" class="active-ticket-notice">
              <p class="notice-title">Active Ticket in Progress</p>
              <p class="notice-desc">
                You already have an active ticket open: <strong>{{ activeOpenTicket.subject }}</strong>. Our team is working on your request. Please reply inside that ticket.
              </p>
              <button type="button" class="btn-primary mt" @click="openTicket(activeOpenTicket.id)">
                Open Active Ticket
              </button>
            </div>
            <form v-else class="form" @submit.prevent="createTicket">
              <label class="form-label">
                Department
                <select v-model="department">
                  <option value="Technical Support">Technical Support (DNS, SSL, Error 500/403)</option>
                  <option value="Billing Support">Billing & Payment Support (MoMo, Invoices)</option>
                  <option value="Hosting Support">Hosting & File Manager Support</option>
                  <option value="Domain & DNS Support">Domain Registration & DNS Setup</option>
                  <option value="General Inquiry">General Inquiry</option>
                </select>
              </label>
              <label class="form-label">
                Subject
                <input v-model="subject" type="text" placeholder="e.g. Need assistance with WordPress database" required />
              </label>
              <label class="form-label">
                Priority
                <select v-model="priority">
                  <option value="low">Low (General question)</option>
                  <option value="normal">Normal (Standard assistance)</option>
                  <option value="high">High (Site down / Urgent)</option>
                </select>
              </label>
              <label class="form-label">
                Message
                <textarea v-model="body" rows="4" placeholder="Describe what is happening, error messages or steps to reproduce…" required />
              </label>
              <button type="submit" class="btn-primary" :disabled="busy">Submit ticket</button>
            </form>
          </div>

          <div class="p-card">
            <h2>Your tickets</h2>
            <p v-if="loading" class="muted mt">Loading…</p>
            <p v-else-if="error" class="err mt">{{ error }}</p>
            <ul v-else class="ticket-list">
              <li v-for="t in tickets" :key="t.id">
                <button type="button" class="ticket-btn" @click="openTicket(t.id)">
                  <span>
                    <span class="subj">{{ t.subject }}</span>
                    <span class="meta">{{ t.status }} · {{ t.priority }}</span>
                  </span>
                  <span class="meta">{{
                    t.updated_at ? new Date(t.updated_at).toLocaleDateString() : ''
                  }}</span>
                </button>
              </li>
              <li v-if="!tickets.length" class="muted pad">No tickets yet.</li>
            </ul>
          </div>
        </section>

        <section class="p-card">
          <h2>Conversation</h2>
          <p v-if="msg" class="muted mt">{{ msg }}</p>
          <p v-if="!selected" class="muted mt">Select a ticket to view messages.</p>
          <template v-else>
            <p class="subj mt">{{ selected.subject }}</p>
            <p class="meta">{{ selected.status }} · {{ selected.priority }}</p>
            <div class="msgs">
              <div
                v-for="m in selected.messages || []"
                :key="m.id"
                class="bubble"
                :class="m.author_role === 'staff' ? 'staff' : 'you'"
              >
                <div class="bubble-head">
                  <p class="role">
                    {{ m.author_role === 'staff' ? '🛡️ Support Specialist' : '👤 You' }}
                  </p>
                  <button
                    type="button"
                    class="copy-btn"
                    title="Copy message"
                    @click="copyText(m.body, m.id)"
                  >
                    {{ copiedMsgId === m.id ? '✓ Copied' : 'Copy' }}
                  </button>
                </div>
                <div
                  class="body"
                  :class="{ 'body-clamped': isLong(m.body) && !isExpanded(m.id) }"
                >
                  {{ m.body }}
                </div>
                <button
                  v-if="isLong(m.body)"
                  type="button"
                  class="read-more-btn"
                  @click="toggleExpand(m.id)"
                >
                  {{ isExpanded(m.id) ? '▲ Show less' : '▼ Read full message' }}
                </button>
                <p class="meta">{{ formatTime(m.created_at) }}</p>
              </div>
            </div>
            <form v-if="selected.status !== 'closed'" class="form mt" @submit.prevent="sendReply">
              <textarea v-model="reply" rows="3" placeholder="Write a reply…" />
              <button type="submit" class="btn-primary" :disabled="busy || !reply.trim()">Send reply</button>
            </form>
            <p v-else class="muted mt">This ticket is closed.</p>
          </template>
        </section>
      </div>
    </div>
  </PortalShell>
  <div v-else class="support-body">
    <div class="head">
      <p class="p-kicker">Help</p>
      <h1>Support</h1>
      <p class="lede">Open a ticket. Staff replies stay in this thread.</p>
    </div>
    <div class="grid">
      <section class="stack">
        <div class="p-card">
          <h2>New ticket</h2>
          <form class="form" @submit.prevent="createTicket">
            <input v-model="subject" type="text" placeholder="Subject" required />
            <select v-model="priority">
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
            </select>
            <textarea v-model="body" rows="4" placeholder="Describe the issue…" required />
            <button type="submit" class="btn-primary" :disabled="busy">Submit ticket</button>
          </form>
        </div>
        <div class="p-card">
          <h2>Your tickets</h2>
          <p v-if="loading" class="muted mt">Loading…</p>
          <p v-else-if="error" class="err mt">{{ error }}</p>
          <ul v-else class="ticket-list">
            <li v-for="t in tickets" :key="t.id">
              <button type="button" class="ticket-btn" @click="openTicket(t.id)">
                <span>
                  <span class="subj">{{ t.subject }}</span>
                  <span class="meta">{{ t.status }} · {{ t.priority }}</span>
                </span>
                <span class="meta">{{
                  t.updated_at ? new Date(t.updated_at).toLocaleDateString() : ''
                }}</span>
              </button>
            </li>
            <li v-if="!tickets.length" class="muted pad">No tickets yet.</li>
          </ul>
        </div>
      </section>
      <section class="p-card">
        <h2>Conversation</h2>
        <p v-if="msg" class="muted mt">{{ msg }}</p>
        <p v-if="!selected" class="muted mt">Select a ticket to view messages.</p>
        <template v-else>
          <p class="subj mt">{{ selected.subject }}</p>
          <p class="meta">{{ selected.status }} · {{ selected.priority }}</p>
          <div class="msgs">
            <div
              v-for="m in selected.messages || []"
              :key="m.id"
              class="bubble"
              :class="m.author_role === 'staff' ? 'staff' : 'you'"
            >
              <div class="bubble-head">
                <p class="role">
                  {{ m.author_role === 'staff' ? '🛡️ Support Specialist' : '👤 You' }}
                </p>
                <button
                  type="button"
                  class="copy-btn"
                  title="Copy message"
                  @click="copyText(m.body, m.id)"
                >
                  {{ copiedMsgId === m.id ? '✓ Copied' : 'Copy' }}
                </button>
              </div>
              <div
                class="body"
                :class="{ 'body-clamped': isLong(m.body) && !isExpanded(m.id) }"
              >
                {{ m.body }}
              </div>
              <button
                v-if="isLong(m.body)"
                type="button"
                class="read-more-btn"
                @click="toggleExpand(m.id)"
              >
                {{ isExpanded(m.id) ? '▲ Show less' : '▼ Read full message' }}
              </button>
              <p class="meta">{{ formatTime(m.created_at) }}</p>
            </div>
          </div>
          <form v-if="selected.status !== 'closed'" class="form mt" @submit.prevent="sendReply">
            <textarea v-model="reply" rows="3" placeholder="Write a reply…" />
            <button type="submit" class="btn-primary" :disabled="busy || !reply.trim()">Send reply</button>
          </form>
          <p v-else class="muted mt">This ticket is closed.</p>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.head h1 {
  margin: 0;
  font-family: Sora, sans-serif;
  font-size: 1.55rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--p-ink, var(--if-ink));
}
.lede {
  margin: 0.35rem 0 0;
  color: var(--p-muted, var(--if-muted));
  font-size: 0.9rem;
}
.mb { margin-bottom: 1rem; }
.hint-grid {
  display: grid;
  gap: 0.85rem;
}
@media (min-width: 700px) {
  .hint-grid { grid-template-columns: 1fr 1fr; }
}
.grid {
  display: grid;
  gap: 1rem;
}
@media (min-width: 900px) {
  .grid { grid-template-columns: 0.95fr 1.05fr; }
}
.stack { display: flex; flex-direction: column; gap: 1rem; }
.p-card h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
}
.form {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  margin-top: 0.75rem;
}
.form input,
.form select,
.form textarea {
  border: 1px solid var(--p-border, var(--if-border));
  border-radius: 0.55rem;
  padding: 0.55rem 0.7rem;
  font: inherit;
  background: #fff;
  color: var(--p-ink, var(--if-ink));
}
.form-label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--p-ink, var(--if-ink));
}
.active-ticket-notice {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 0.75rem;
  padding: 1rem;
}
:root.dark .active-ticket-notice {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.25);
}
.notice-title {
  font-weight: 700;
  font-size: 0.9rem;
  color: #166534;
  margin: 0 0 0.35rem;
}
:root.dark .notice-title {
  color: #4ade80;
}
.notice-desc {
  font-size: 0.82rem;
  color: #15803d;
  line-height: 1.4;
  margin: 0;
}
:root.dark .notice-desc {
  color: #86efac;
}
.btn-primary {
  border: none;
  border-radius: 0.55rem;
  background: var(--p-accent, var(--if-primary));
  color: #fff;
  font-weight: 650;
  font-size: 0.85rem;
  padding: 0.55rem 0.9rem;
  cursor: pointer;
  width: fit-content;
}
.nav-text {
  border: none;
  background: transparent;
  color: var(--p-muted, var(--if-muted));
  font-size: 0.85rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.35rem 0.6rem;
}
.ticket-list { list-style: none; margin: 0.65rem 0 0; padding: 0; }
.ticket-btn {
  width: 100%;
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  border: 1px solid var(--p-border, var(--if-border));
  border-radius: 0.7rem;
  background: #fff;
  padding: 0.7rem 0.8rem;
  margin-bottom: 0.45rem;
  cursor: pointer;
  text-align: left;
}
.ticket-btn:hover {
  border-color: color-mix(in srgb, var(--p-accent, var(--if-plan)) 40%, var(--p-border, var(--if-border)));
}
.subj { display: block; font-weight: 650; color: var(--p-ink, var(--if-ink)); }
.meta { display: block; font-size: 0.72rem; color: var(--p-muted, var(--if-muted)); margin-top: 0.15rem; }
.msgs { margin-top: 0.85rem; display: flex; flex-direction: column; gap: 0.55rem; max-height: 22rem; overflow: auto; }
.bubble {
  border-radius: 0.75rem;
  padding: 0.7rem 0.8rem;
  background: color-mix(in srgb, var(--p-border, var(--if-border)) 40%, white);
}
.bubble.you {
  background: color-mix(in srgb, var(--p-accent, var(--if-plan)) 12%, white);
}
.bubble.staff {
  background: #f4f6f8;
}
.role { margin: 0; font-size: 0.68rem; font-weight: 700; text-transform: uppercase; color: var(--p-accent, var(--if-plan)); }
.bubble-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem; }
.copy-btn { border: none; background: rgba(0,0,0,0.06); border-radius: 0.35rem; font-size: 0.68rem; padding: 0.15rem 0.4rem; cursor: pointer; color: var(--p-muted, var(--if-muted)); }
.copy-btn:hover { background: rgba(0,0,0,0.12); color: var(--p-ink, var(--if-ink)); }
.body { margin: 0.25rem 0 0; font-size: 0.875rem; white-space: pre-wrap; word-break: break-word; }
.body-clamped {
  display: -webkit-box;
  -webkit-line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.read-more-btn {
  background: none;
  border: none;
  padding: 0.3rem 0;
  margin-top: 0.35rem;
  color: var(--p-accent, var(--if-plan));
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
}
.read-more-btn:hover { opacity: 0.85; }
.muted { color: var(--p-muted, var(--if-muted)); font-size: 0.85rem; margin: 0; }
.err { color: #b91c1c; font-size: 0.85rem; }
.mt { margin-top: 0.75rem; }
.pad { padding: 0.75rem 0; }
</style>
