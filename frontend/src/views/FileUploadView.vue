<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import Card from '@/components/ui/Card.vue'
import FileTransferQueue from '@/components/files/FileTransferQueue.vue'
import { filesApi } from '@/api'
import { useFileTransferStore } from '@/stores/fileTransfers'
import { usePermissions } from '@/composables/usePermissions'
import { Permission } from '@/lib/permissions'
import type { FileRoot } from '@/types/hosting'

const route = useRoute()
const transfers = useFileTransferStore()
const { can } = usePermissions()
const canWrite = computed(() => can(Permission.FILES_WRITE))

const roots = ref<FileRoot[]>([])
const selectedRoot = ref(String(route.query.root ?? ''))
const targetPath = ref(String(route.query.path ?? '.'))
const dragOver = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const pendingFiles = ref<File[]>([])

const scope = computed(() => {
  if (!selectedRoot.value) return {}
  if (selectedRoot.value.startsWith('root:') || selectedRoot.value.startsWith('discovered:')) {
    return { rootId: selectedRoot.value }
  }
  return { appId: selectedRoot.value }
})

const activeRoot = computed(() => roots.value.find((r) => r.id === selectedRoot.value))

const destinationLabel = computed(() => {
  const base = activeRoot.value?.path ?? ''
  const sub = targetPath.value === '.' ? '' : `/${targetPath.value}`
  return `${base}${sub}`
})

onMounted(async () => {
  const { data } = await filesApi.roots()
  roots.value = data.roots
  if (!selectedRoot.value && roots.value.length) {
    selectedRoot.value = roots.value[0].id
  }
})

function addFiles(files: FileList | File[]) {
  pendingFiles.value.push(...Array.from(files))
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

function startQueue() {
  if (!pendingFiles.value.length || !canWrite.value) return
  transfers.enqueueUploadMany([...pendingFiles.value], targetPath.value, scope.value)
  pendingFiles.value = []
}

function formatBytes(n: number) {
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}

const backQuery = computed(() => ({
  root: selectedRoot.value,
  path: targetPath.value,
}))
</script>

<template>
  <DashboardLayout>
    <div class="animate-fade-in mx-auto max-w-3xl space-y-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 class="text-lg font-semibold text-slate-900 dark:text-white">Upload files</h1>
          <p class="text-sm text-surface-muted">Queued, chunked uploads — safe for large files</p>
        </div>
        <RouterLink
          :to="{ name: 'files', query: backQuery }"
          class="rounded-lg border border-surface-border px-3 py-2 text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
        >
          ← Back to files
        </RouterLink>
      </div>

      <Card padding="md">
        <label class="block text-sm">
          <span class="text-surface-muted">Destination root</span>
          <select
            v-model="selectedRoot"
            class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2"
          >
            <option v-for="root in roots" :key="root.id" :value="root.id">{{ root.label }} — {{ root.path }}</option>
          </select>
        </label>
        <label class="mt-3 block text-sm">
          <span class="text-surface-muted">Folder path</span>
          <input
            v-model="targetPath"
            class="mt-1 w-full rounded-lg border border-surface-border bg-transparent px-3 py-2 font-mono text-sm"
            placeholder="."
          />
        </label>
        <p class="mt-2 font-mono text-xs text-surface-muted">Uploading to: {{ destinationLabel }}</p>
      </Card>

      <div
        class="rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors"
        :class="
          dragOver
            ? 'border-brand-500 bg-brand-500/5'
            : 'border-surface-border bg-surface-raised hover:border-brand-500/40'
        "
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop.prevent="onDrop"
      >
        <p class="text-sm font-medium text-slate-900 dark:text-white">Drop files here</p>
        <p class="mt-1 text-xs text-surface-muted">or</p>
        <button
          type="button"
          class="mt-3 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          @click="fileInput?.click()"
        >
          Choose files
        </button>
        <input ref="fileInput" type="file" multiple class="hidden" @change="onPick" />
      </div>

      <Card v-if="pendingFiles.length" padding="md">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold">Ready to upload ({{ pendingFiles.length }})</h2>
          <button
            type="button"
            class="rounded-lg bg-brand-600 px-3 py-2 text-sm text-white disabled:opacity-50"
            :disabled="!canWrite"
            @click="startQueue"
          >
            Add to queue
          </button>
        </div>
        <ul class="space-y-2">
          <li
            v-for="(file, index) in pendingFiles"
            :key="`${file.name}-${index}`"
            class="flex items-center justify-between rounded-lg border border-surface-border px-3 py-2 text-sm"
          >
            <span class="truncate">{{ file.name }}</span>
            <div class="flex items-center gap-3">
              <span class="text-xs text-surface-muted">{{ formatBytes(file.size) }}</span>
              <button type="button" class="text-xs text-red-600" @click="removePending(index)">Remove</button>
            </div>
          </li>
        </ul>
      </Card>

      <FileTransferQueue />
    </div>
  </DashboardLayout>
</template>
