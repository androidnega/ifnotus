<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { catalogApi } from '@/api'
import SiteHeader from '@/components/site/SiteHeader.vue'
import { useSiteTheme } from '@/composables/useSiteTheme'

const { load: loadTheme } = useSiteTheme()
const message = ref('IFNOTUS is under scheduled maintenance. Please check back shortly.')
const support = ref('')

onMounted(async () => {
  await loadTheme()
  try {
    const { data } = await catalogApi.meta()
    if (data.maintenance_message) message.value = data.maintenance_message
    support.value = data.support_whatsapp || data.support_email || ''
  } catch {
    /* keep defaults */
  }
})
</script>

<template>
  <div class="maint">
    <SiteHeader />
    <main class="card">
      <p class="eyebrow">Maintenance</p>
      <h1>We’ll be right back</h1>
      <p class="lede">{{ message }}</p>
      <p v-if="support" class="hint">Need help? {{ support }}</p>
    </main>
  </div>
</template>

<style scoped>
.maint {
  min-height: 100vh;
  background: var(--if-paper, #f4f1ec);
  color: var(--if-ink, #161a1d);
}
.card {
  max-width: 34rem;
  margin: 4rem auto;
  padding: 2rem 1.5rem;
}
.eyebrow {
  margin: 0;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--if-primary, #ff6c2c);
}
h1 {
  margin: 0.5rem 0 0;
  font-family: Sora, sans-serif;
  font-size: clamp(1.6rem, 3vw, 2.1rem);
  letter-spacing: -0.03em;
}
.lede, .hint {
  margin: 0.85rem 0 0;
  color: var(--if-muted, #6b7280);
  line-height: 1.5;
}
</style>
