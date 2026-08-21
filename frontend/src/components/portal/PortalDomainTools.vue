<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { customersApi } from '@/api'

const props = defineProps<{
  environmentId: string
  canRedirects?: boolean
  canGit?: boolean
  reposLimit?: number | null
  mailboxesLimit?: number | null
}>()

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
const msg = ref('')
const busy = ref(false)

async function load() {
  msg.value = ''
  try {
    const [r, z, g] = await Promise.all([
      customersApi.listEnvRedirects(props.environmentId),
      customersApi.getEnvZone(props.environmentId),
      customersApi.getEnvGit(props.environmentId),
    ])
    redirects.value = r.data || []
    zone.value = z.data
    git.value = g.data
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Could not load domain tools.'
  }
}

async function addRedirect() {
  if (!redirectsOn.value) return
  busy.value = true
  msg.value = ''
  try {
    await customersApi.createEnvRedirect(props.environmentId, {
      source_path: redirSource.value.trim(),
      target_url: redirTarget.value.trim(),
      status_code: redirCode.value,
    })
    await load()
    msg.value = 'Redirect saved.'
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Could not create redirect.'
  } finally {
    busy.value = false
  }
}

async function removeRedirect(id: string) {
  busy.value = true
  try {
    await customersApi.deleteEnvRedirect(props.environmentId, id)
    await load()
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Could not remove redirect.'
  } finally {
    busy.value = false
  }
}

async function addZone() {
  busy.value = true
  msg.value = ''
  try {
    await customersApi.createEnvZoneRecord(props.environmentId, {
      record_type: zoneType.value,
      host: zoneHost.value.trim() || '@',
      value: zoneValue.value.trim(),
    })
    zoneValue.value = ''
    await load()
    msg.value = 'DNS record saved.'
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Could not add DNS record.'
  } finally {
    busy.value = false
  }
}

async function cloneGit() {
  if (!gitOn.value) return
  busy.value = true
  msg.value = ''
  try {
    const { data } = await customersApi.cloneEnvGit(props.environmentId, {
      repo_url: gitUrl.value.trim(),
      branch: gitBranch.value.trim() || undefined,
    })
    git.value = data
    msg.value = data.message || 'Repository cloned.'
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Clone failed.'
  } finally {
    busy.value = false
  }
}

async function pullGit() {
  busy.value = true
  msg.value = ''
  try {
    const { data } = await customersApi.pullEnvGit(props.environmentId)
    git.value = data
    msg.value = data.message || 'Pulled.'
  } catch (e: unknown) {
    const x = e as { response?: { data?: { error?: { message?: string } } } }
    msg.value = x.response?.data?.error?.message ?? 'Pull failed.'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="tools">
    <p v-if="msg" class="hint">{{ msg }}</p>

    <section v-if="redirectsOn" class="block">
      <h3>Redirects</h3>
      <p class="muted">Send a path on this site to another URL.</p>
      <form class="form-row mt" @submit.prevent="addRedirect">
        <input v-model="redirSource" class="input" placeholder="/old" required />
        <input v-model="redirTarget" class="input grow" placeholder="https://…" required />
        <select v-model.number="redirCode" class="input">
          <option :value="301">301</option>
          <option :value="302">302</option>
        </select>
        <button type="submit" class="btn-primary" :disabled="busy">Add</button>
      </form>
      <ul v-if="redirects.length" class="job-list mt">
        <li v-for="r in redirects" :key="r.id">
          <span>{{ r.status_code }} {{ r.source_path }} → {{ r.target_url }}</span>
          <button type="button" class="btn-ghost" @click="removeRedirect(r.id)">Remove</button>
        </li>
      </ul>
      <p v-else class="hint mt">No redirects yet.</p>
    </section>
    <section v-else class="block muted-block">
      <h3>Redirects</h3>
      <p class="muted">Not included on this package.</p>
    </section>

    <section class="block">
      <h3>DNS</h3>
      <p class="muted">{{ zone?.message || 'DNS records for this domain.' }}</p>
      <ul v-if="zone?.records?.length" class="job-list mt">
        <li v-for="rec in zone.records" :key="rec.id">
          <span class="mono">{{ rec.record_type }} {{ rec.host }} → {{ rec.value }}</span>
        </li>
      </ul>
      <form v-if="zone?.editable" class="form-row mt" @submit.prevent="addZone">
        <select v-model="zoneType" class="input">
          <option>A</option>
          <option>AAAA</option>
          <option>CNAME</option>
          <option>MX</option>
          <option>TXT</option>
        </select>
        <input v-model="zoneHost" class="input" placeholder="@" />
        <input v-model="zoneValue" class="input grow" placeholder="value" required />
        <button type="submit" class="btn-primary" :disabled="busy">Add record</button>
      </form>
    </section>

    <section v-if="gitOn" class="block">
      <h3>Git</h3>
      <p class="muted">
        <template v-if="reposLimit === 1">This package includes 1 Git repository for this site.</template>
        <template v-else-if="reposLimit">This package includes up to {{ reposLimit }} Git repositories.</template>
        <template v-else>Clone a public repo into this site folder, then pull updates.</template>
      </p>
      <template v-if="git?.configured">
        <p class="hint mt wrap">{{ git.remote }} · {{ git.branch }} · {{ git.commit }}</p>
        <button type="button" class="btn-primary mt" :disabled="busy" @click="pullGit">Pull</button>
      </template>
      <form v-else class="form-row mt" @submit.prevent="cloneGit">
        <input v-model="gitUrl" class="input grow" placeholder="https://github.com/you/repo.git" required />
        <input v-model="gitBranch" class="input" placeholder="main" />
        <button type="submit" class="btn-primary" :disabled="busy">Clone</button>
      </form>
    </section>
    <section v-else class="block muted-block">
      <h3>Git</h3>
      <p class="muted">Not included on this package.</p>
    </section>
  </div>
</template>

<style scoped>
.tools { display: flex; flex-direction: column; gap: 1rem; }
.block {
  border: 1px solid var(--if-border, #d7dee8);
  border-radius: 1rem;
  padding: 1.1rem 1.2rem;
  background: var(--if-surface, #fff);
  min-width: 0;
}
.muted-block { opacity: 0.72; }
h3 { margin: 0; }
.muted { margin: 0.35rem 0 0; color: #5c6670; font-size: 0.9rem; }
.hint { margin: 0.45rem 0 0; font-size: 0.84rem; color: #5c6670; }
.wrap { overflow-wrap: anywhere; word-break: break-word; }
.mt { margin-top: 0.7rem; }
.form-row { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.input {
  border: 1px solid var(--if-border, #d8dee4);
  border-radius: 0.6rem;
  padding: 0.45rem 0.65rem;
  font: inherit;
  min-width: 0;
}
.input.grow { flex: 1 1 12rem; }
.btn-primary, .btn-ghost {
  border: 0;
  border-radius: 0.6rem;
  padding: 0.45rem 0.8rem;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}
.btn-primary { background: var(--p-accent, #1e3a5f); color: #fff; }
.btn-ghost { background: transparent; border: 1px solid var(--if-border, #d8dee4); }
.job-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.job-list li {
  display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.5rem;
  font-size: 0.84rem; overflow-wrap: anywhere;
}
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.78rem; overflow-wrap: anywhere; }
</style>
