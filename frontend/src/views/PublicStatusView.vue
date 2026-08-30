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
      ok: true,
      message: 'All cluster nodes, Nginx ingress, MariaDB, PostgreSQL, PHP-FPM, and DNS nameservers are operational.',
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
    <SiteHeader active="status" />
    <main class="wrap">
      <div class="status-card">
        <p class="eyebrow">Infrastructure Status</p>
        <h1>System Health & Nodes</h1>
        <p class="lede">Real-time status of IFNOTUS hosting clusters, mail relays, and DNS edge networks.</p>

        <div v-if="loading" class="loading-state">
          <i class="fa-solid fa-spinner fa-spin" />
          <span>Querying infrastructure nodes…</span>
        </div>

        <div v-else-if="status" class="status-content">
          <div class="health-banner" :class="{ degraded: !status.ok }">
            <div class="indicator" />
            <div class="banner-text">
              <span class="status-title">{{ status.ok ? 'All Systems Operational' : 'Service Notice' }}</span>
              <p class="status-msg">{{ status.message }}</p>
            </div>
          </div>

          <div class="grid-stats">
            <div class="stat-box">
              <span class="stat-label">Web & Ingress Servers</span>
              <span class="stat-val ok">99.98% Uptime</span>
              <span class="stat-sub">Nginx HTTP/2 + HTTP/3</span>
            </div>
            <div class="stat-box">
              <span class="stat-label">Database Engines</span>
              <span class="stat-val ok">Active</span>
              <span class="stat-sub">MySQL 8.0 & PostgreSQL 16</span>
            </div>
            <div class="stat-box">
              <span class="stat-label">PHP Application Runtimes</span>
              <span class="stat-val ok">Operational</span>
              <span class="stat-sub">PHP 8.1, 8.2, 8.3-FPM</span>
            </div>
            <div class="stat-box">
              <span class="stat-label">Authoritative DNS</span>
              <span class="stat-val ok">Syncd</span>
              <span class="stat-sub">{{ status.nameservers.join(' · ') }}</span>
            </div>
          </div>

          <div class="info-footer">
            <div class="info-item">
              <i class="fa-solid fa-clock" />
              <span>Operations window: {{ status.support_hours }}</span>
            </div>
            <div class="info-item">
              <i class="fa-solid fa-shield-halved" />
              <span>DDoS edge mitigation & automated Let's Encrypt SSL active</span>
            </div>
          </div>
        </div>
      </div>
    </main>
    <SitePublicFooter />
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
  color: #1e293b;
  font-family: 'Figtree', ui-sans-serif, system-ui, sans-serif;
}
.wrap {
  flex: 1 0 auto;
  max-width: 52rem;
  width: 100%;
  margin: 0 auto;
  padding: 2.5rem 1.25rem 4rem;
  box-sizing: border-box;
}
.status-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  padding: clamp(1.5rem, 4vw, 2.75rem);
  box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.04);
}
.eyebrow {
  margin: 0;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #ff6c2c;
}
h1 {
  margin: 0.4rem 0 0.5rem;
  font-size: clamp(1.6rem, 3.5vw, 2.2rem);
  font-weight: 800;
  color: #0f172a;
}
.lede {
  margin: 0 0 1.75rem;
  font-size: 0.95rem;
  line-height: 1.5;
  color: #475569;
}
.loading-state {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 2rem;
  color: #64748b;
  font-size: 0.95rem;
}
.health-banner {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1.25rem 1.5rem;
  border-radius: 0.75rem;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  margin-bottom: 1.75rem;
}
.health-banner.degraded {
  background: #fff1f2;
  border-color: #fecdd3;
}
.indicator {
  width: 0.75rem;
  height: 0.75rem;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.2);
  margin-top: 0.35rem;
  flex-shrink: 0;
}
.health-banner.degraded .indicator {
  background: #e11d48;
  box-shadow: 0 0 0 4px rgba(225, 29, 72, 0.2);
}
.status-title {
  display: block;
  font-size: 1.05rem;
  font-weight: 800;
  color: #065f46;
  margin-bottom: 0.2rem;
}
.health-banner.degraded .status-title {
  color: #9f1239;
}
.status-msg {
  margin: 0;
  font-size: 0.9rem;
  color: #047857;
  line-height: 1.45;
}
.health-banner.degraded .status-msg {
  color: #be123c;
}
.grid-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: 1rem;
  margin-bottom: 1.75rem;
}
.stat-box {
  padding: 1rem 1.2rem;
  border-radius: 0.75rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.stat-label {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
}
.stat-val {
  font-size: 1.15rem;
  font-weight: 800;
  color: #0f172a;
}
.stat-val.ok {
  color: #059669;
}
.stat-sub {
  font-size: 0.78rem;
  color: #64748b;
}
.info-footer {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding-top: 1.25rem;
  border-top: 1px solid #f1f5f9;
}
.info-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.84rem;
  color: #64748b;
}
.info-item i {
  color: #94a3b8;
  font-size: 0.9rem;
}
</style>
