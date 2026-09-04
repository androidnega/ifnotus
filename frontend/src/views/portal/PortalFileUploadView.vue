<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import FileTransferQueue from '@/components/files/FileTransferQueue.vue'
import { customersApi } from '@/api'
import { useFileTransferStore } from '@/stores/fileTransfers'

const route = useRoute()
const transfers = useFileTransferStore()

const envId = computed(() => String(route.query.env || ''))
const targetPath = ref(String(route.query.path || '.'))
const domain = ref('')
const dragOver = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const pendingFiles = ref<File[]>([])
const err = ref('')
const MAX_UPLOAD_SIZE = 512 * 1024 * 1024 // 512 MB

onMounted(async () => {
  if (!envId.value) {
    err.value = 'Missing site.'
    return
  }
  try {
    const { data } = await customersApi.dashboard()
    const env = data.environments.find((e) => e.id === envId.value)
    domain.value = env?.domain || ''
  } catch {
    /* non-fatal */
  }
})

function addFiles(files: FileList | File[]) {
  err.value = ''
  const list = Array.from(files)
  const valid: File[] = []
  for (const f of list) {
    if (f.size > MAX_UPLOAD_SIZE) {
      err.value = `${f.name} exceeds the maximum upload limit of 512 MB.`
    } else {
      valid.push(f)
    }
  }
  pendingFiles.value.push(...valid)
}

function onDrop(ev: DragEvent) {
  dragOver.value = false
  if (ev.dataTransfer?.files?.length) addFiles(ev.dataTransfer.files)
}

function onPick(ev: Event) {
  const input = ev.target as HTMLInputElement
  if (input.files?.length) addFiles(input.files)
  input.value = ''
}

function removePending(index: number) {
  pendingFiles.value.splice(index, 1)
}

async function startQueue() {
  if (!pendingFiles.value.length || !envId.value) return
  err.value = ''
  // Check destination for duplicates before uploading
  let existing = new Set<string>()
  try {
    const { data } = await customersApi.listEnvFiles(envId.value, targetPath.value || '.')
    existing = new Set(
      (data.entries || []).filter((e) => !e.is_dir).map((e) => e.name.toLowerCase()),
    )
  } catch {
    /* non-fatal — proceed without check */
  }
  const duplicates = pendingFiles.value.filter((f) => existing.has(f.name.toLowerCase()))
  let files = [...pendingFiles.value]
  if (duplicates.length) {
    const names = duplicates.map((f) => f.name).slice(0, 5).join(', ')
    const more = duplicates.length > 5 ? ` (+${duplicates.length - 5} more)` : ''
    const ok = window.confirm(
      `${duplicates.length} file(s) already exist (${names}${more}).\n\nOK = replace\nCancel = skip duplicates`,
    )
    if (!ok) {
      const dupSet = new Set(duplicates.map((f) => f.name.toLowerCase()))
      files = files.filter((f) => !dupSet.has(f.name.toLowerCase()))
      if (!files.length) {
        err.value = 'Upload cancelled — duplicates skipped.'
        return
      }
    }
  }
  transfers.enqueueUploadMany(files, targetPath.value || '.', {
    environmentId: envId.value,
  })
  pendingFiles.value = []
}

function formatBytes(n: number) {
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}

function backToFiles() {
  const href = `/hosting/${encodeURIComponent(envId.value)}/files?path=${encodeURIComponent(targetPath.value || '.')}`
  window.location.href = href
}
</script>

<template>
  <div class="up-shell">
    <header class="up-top">
      <div class="brand">
        <a href="/account" class="mark">IF</a>
        <div>
          <strong>Upload</strong>
          <p>{{ domain || 'Your site' }} · {{ targetPath === '.' ? 'site root' : targetPath }}</p>
        </div>
      </div>
      <div class="actions">
        <button type="button" class="ghost" @click="backToFiles">Back to files</button>
      </div>
    </header>

    <main class="up-main">
      <p v-if="err" class="bad">{{ err }}</p>

      <section class="card">
        <h1>Upload queue</h1>
        <p class="lede">
          Supports .zip archives and files up to 512 MB. Files upload one at a time in chunks so large transfers do not time out. Keep this page open until the queue finishes.
        </p>

        <label class="field">
          <span>Destination folder</span>
          <input v-model="targetPath" type="text" placeholder="." />
        </label>

        <div
          class="drop"
          :class="{ over: dragOver }"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="onDrop"
        >
          <p>Drop files here or choose files</p>
          <button type="button" class="primary" @click="fileInput?.click()">Choose files</button>
          <input ref="fileInput" type="file" class="hidden" multiple @change="onPick" />
        </div>

        <ul v-if="pendingFiles.length" class="pending">
          <li v-for="(f, i) in pendingFiles" :key="`${f.name}-${i}`">
            <span>{{ f.name }} · {{ formatBytes(f.size) }}</span>
            <button type="button" class="link" @click="removePending(i)">Remove</button>
          </li>
        </ul>

        <button
          type="button"
          class="primary wide"
          :disabled="!pendingFiles.length || !envId"
          @click="startQueue"
        >
          Start upload queue
        </button>
      </section>

      <FileTransferQueue />
    </main>
  </div>
</template>

<style scoped>
.up-shell {
  min-height: 100vh;
  background: linear-gradient(180deg, #eef3f8 0%, #f8fafc 40%);
  color: #0f172a;
}
.up-top {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: center;
  padding: 0.85rem 1.1rem;
  border-bottom: 1px solid #d7dee8;
  background: rgba(255, 255, 255, 0.92);
}
.brand { display: flex; gap: 0.65rem; align-items: center; }
.mark {
  width: 2rem;
  height: 2rem;
  border-radius: 0.45rem;
  display: grid;
  place-items: center;
  background: #1e3a5f;
  color: #fff;
  font-weight: 800;
  font-size: 0.7rem;
  text-decoration: none;
}
.brand strong { display: block; font-size: 0.95rem; }
.brand p { margin: 0; font-size: 0.75rem; color: #64748b; }
.ghost {
  border: 1px solid #d7dee8;
  background: #fff;
  border-radius: 0.45rem;
  padding: 0.45rem 0.75rem;
  font-size: 0.82rem;
  font-weight: 650;
  cursor: pointer;
}
.up-main {
  max-width: 52rem;
  margin: 0 auto;
  padding: 1.25rem 1rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.card {
  border: 1px solid #d7dee8;
  border-radius: 1rem;
  background: #fff;
  padding: 1.1rem 1.15rem;
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.05);
}
.card h1 { margin: 0; font-size: 1.25rem; }
.lede { margin: 0.45rem 0 1rem; color: #64748b; font-size: 0.9rem; line-height: 1.45; }
.field { display: flex; flex-direction: column; gap: 0.35rem; margin-bottom: 0.85rem; font-size: 0.8rem; font-weight: 650; }
.field input {
  border: 1px solid #d7dee8;
  border-radius: 0.5rem;
  padding: 0.55rem 0.65rem;
  font: inherit;
  font-weight: 500;
}
.drop {
  border: 1.5px dashed #cbd5e1;
  border-radius: 0.85rem;
  padding: 1.4rem 1rem;
  text-align: center;
  background: #f8fafc;
  margin-bottom: 0.85rem;
}
.drop.over { border-color: #1e3a5f; background: #eef3f8; }
.drop p { margin: 0 0 0.75rem; color: #64748b; font-size: 0.88rem; }
.primary {
  border: none;
  border-radius: 0.5rem;
  background: #1e3a5f;
  color: #fff;
  font-weight: 650;
  font-size: 0.85rem;
  padding: 0.55rem 0.9rem;
  cursor: pointer;
}
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.primary.wide { width: 100%; margin-top: 0.35rem; }
.hidden { display: none; }
.pending { list-style: none; margin: 0 0 0.75rem; padding: 0; display: flex; flex-direction: column; gap: 0.35rem; }
.pending li {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.82rem;
  padding: 0.45rem 0.55rem;
  border-radius: 0.45rem;
  background: #f1f5f9;
}
.link { border: none; background: none; color: #b91c1c; cursor: pointer; font-size: 0.75rem; }
.bad { color: #b91c1c; font-size: 0.88rem; }
</style>
