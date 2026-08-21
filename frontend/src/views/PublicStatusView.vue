<script setup lang="ts">
import { onMounted, ref } from 'vue'
import SiteHeader from '@/components/site/SiteHeader.vue'
import SitePublicFooter from '@/components/site/SitePublicFooter.vue'
import { catalogApi } from '@/api'

const loading = ref(true)
const status = ref<{ ok: boolean; message: string; nameservers: string[]; support_hours: string } | null>(
  null,
)

onMounted(async () => {
  try {
    const { data } = await catalogApi.status()
    status.value = data
  } catch {
    status.value = {
      ok: false,
      message: 'We could not reach status right now. Email support@ifnotus.space.',
      nameservers: ['ns1.ifnotus.space', 'ns2.ifnotus.space'],
      support_hours: 'Monday–Saturday, 08:00–20:00 GMT',
    }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page">
    <SiteHeader />
    <main class="wrap">
      <p class="eyebrow">Status</p>
      <h1>Service status</h1>
      <p v-if="loading">Checking…</p>
      <div v-else-if="status" class="card" :class="{ down: !status.ok }">
        <p class="pill">{{ status.ok ? 'Operating normally' : 'Check with support' }}</p>
        <p>{{ status.message }}</p>
        <p class="muted">Support hours: {{ status.support_hours }}</p>
        <p class="muted">Nameservers: {{ status.nameservers.join(' · ') }}</p>
      </div>
    </main>
    <SitePublicFooter />
  </div>
</template>

<style scoped>
.page { min-height: 100vh; background: #f6f7f9; }
.wrap { max-width: 40rem; margin: 0 auto; padding: 2rem 1.2rem 4rem; }
.eyebrow { margin: 0; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: #ff6c2c; }
h1 { margin: 0.35rem 0 1rem; }
.card { background: #fff; border: 1px solid #e4e8ec; border-radius: 1rem; padding: 1.2rem; }
.card.down { border-color: #f5c2c0; }
.pill { font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: #0f7a45; }
.muted { color: #5c6670; font-size: 0.9rem; }
</style>
