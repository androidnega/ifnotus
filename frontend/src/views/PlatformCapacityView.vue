<script setup lang="ts">
import { onMounted, ref } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { platformAdminApi } from '@/api'

type CapacityNode = {
  node_id: string
  hostname: string
  cpu_total: number
  ram_total_gb: number
  storage_total_gb: number
  cpu_reserved_pct: number
  cpu_used: number
  ram_used: number
  storage_used: number
  cpu_free: number
  ram_free: number
  storage_free: number
  status: string
}

const nodes = ref<CapacityNode[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await platformAdminApi.listCapacity()
    nodes.value = data
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not load capacity.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <DashboardLayout>
    <div class="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">Shared node capacity</h1>
          <p class="mt-1 text-sm text-slate-600 dark:text-slate-400">
            CPU, RAM, and storage headroom for managed packs on this host.
          </p>
        </div>
        <button type="button" class="rounded border border-slate-300 px-3 py-1.5 text-sm" @click="load">
          Refresh
        </button>
      </div>

      <p v-if="loading" class="text-sm text-slate-500">Loading…</p>
      <p v-else-if="error" class="text-sm text-red-600">{{ error }}</p>
      <p v-else-if="!nodes.length" class="text-sm text-slate-500">No infrastructure nodes registered yet.</p>

      <div v-else class="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
        <table class="min-w-full text-left text-sm">
          <thead class="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-700 dark:bg-slate-900">
            <tr>
              <th class="px-3 py-2 font-medium">Node</th>
              <th class="px-3 py-2 font-medium">Status</th>
              <th class="px-3 py-2 font-medium">CPU free</th>
              <th class="px-3 py-2 font-medium">RAM free</th>
              <th class="px-3 py-2 font-medium">Storage free</th>
              <th class="px-3 py-2 font-medium">Reserved CPU %</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="n in nodes"
              :key="n.node_id"
              class="border-b border-slate-100 dark:border-slate-800"
            >
              <td class="px-3 py-2 font-medium text-slate-900 dark:text-slate-100">{{ n.hostname }}</td>
              <td class="px-3 py-2 capitalize">{{ n.status }}</td>
              <td class="px-3 py-2">{{ Number(n.cpu_free).toFixed(2) }} / {{ n.cpu_total }}</td>
              <td class="px-3 py-2">{{ Number(n.ram_free).toFixed(2) }} / {{ n.ram_total_gb }} GB</td>
              <td class="px-3 py-2">{{ n.storage_free }} / {{ n.storage_total_gb }} GB</td>
              <td class="px-3 py-2">{{ n.cpu_reserved_pct }}%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </DashboardLayout>
</template>
