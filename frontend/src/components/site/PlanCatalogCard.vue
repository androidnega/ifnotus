<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { HostingPlan } from '@/types/platform'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { packItems } from '@/lib/planPack'
import { sshHeadline } from '@/lib/planMatrix'
import { planAccentFromPrice, softAccent } from '@/lib/theme'
import { useSiteTheme } from '@/composables/useSiteTheme'

const props = defineProps<{
  plan: HostingPlan
  featured?: boolean
}>()

const { planColors } = useSiteTheme()

const accent = computed(() =>
  planAccentFromPrice(Number(props.plan.price_monthly), planColors.value, props.plan.features),
)

const cardStyle = computed(() => ({
  '--plan-accent': accent.value,
  '--plan-accent-soft': softAccent(accent.value, 0.12),
}))

const highlights = computed(() => packItems(props.plan))
const preview = computed(() => highlights.value.slice(0, 4))

function priceLabel() {
  const n = Number(props.plan.price_monthly)
  return Number.isInteger(n) ? String(n) : String(n)
}
</script>

<template>
  <article class="plan" :class="{ featured }" :style="cardStyle">
    <header class="plan-head">
      <div>
        <h2>{{ plan.name }}</h2>
        <p class="ssh">{{ sshHeadline(plan) }}</p>
      </div>
      <span v-if="plan.catalog_card?.product_status === 'coming_soon'" class="badge soon">Soon</span>
      <span v-else-if="featured" class="badge">Popular</span>
    </header>

    <p class="price">
      <span class="cur">₵</span>
      <span class="amt">{{ priceLabel() }}</span>
      <span class="unit">/ month</span>
    </p>

    <div class="metrics">
      <div class="metric">
        <i class="fa-solid fa-microchip" aria-hidden="true" />
        <span>{{ formatCpu(plan.cpu_cores) }} vCPU</span>
      </div>
      <div class="metric">
        <i class="fa-solid fa-memory" aria-hidden="true" />
        <span>{{ formatRamGb(plan.ram_gb) }}</span>
      </div>
      <div class="metric">
        <i class="fa-solid fa-hard-drive" aria-hidden="true" />
        <span>{{ plan.storage_gb }} GB</span>
      </div>
      <div class="metric">
        <i class="fa-solid fa-robot" aria-hidden="true" />
        <span>{{ plan.ai_credits }} AI</span>
      </div>
    </div>

    <ul class="highlights">
      <li v-for="item in preview" :key="item.id">
        <i class="fa-solid fa-check" aria-hidden="true" />
        <span><strong>{{ item.label }}</strong> — {{ item.detail }}</span>
      </li>
    </ul>

    <RouterLink :to="{ name: 'plan-detail', params: { slug: plan.slug } }" class="cta">
      Get {{ plan.name }}
      <i class="fa-solid fa-arrow-right" aria-hidden="true" />
    </RouterLink>
  </article>
</template>

<style scoped>
.plan {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  min-height: 100%;
  padding: 1.15rem 1.1rem 1.1rem;
  border: 1px solid var(--if-border, #e7e2db);
  border-radius: 1rem;
  background: var(--if-surface, #fff);
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.04);
  border-top: 3px solid var(--plan-accent, var(--if-primary, #ff6c2c));
}
.plan.featured {
  background: linear-gradient(180deg, var(--plan-accent-soft) 0%, var(--if-surface, #fff) 42%);
  box-shadow: 0 8px 24px rgb(15 23 42 / 0.08);
}
.plan-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}
.plan-head h2 {
  margin: 0;
  font-family: 'Sora', sans-serif;
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--if-ink, #161a1d);
}
.ssh {
  margin: 0.2rem 0 0;
  font-size: 0.72rem;
  font-weight: 650;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
}
.badge {
  flex-shrink: 0;
  font-size: 0.62rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
  background: var(--plan-accent-soft, rgba(255, 108, 44, 0.12));
  border-radius: 999px;
  padding: 0.2rem 0.5rem;
}
.badge.soon {
  color: #64748b;
  background: #f1f5f9;
}
.price {
  margin: 0;
  display: flex;
  align-items: baseline;
  gap: 0.1rem;
  font-family: 'Sora', sans-serif;
}
.cur {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
}
.amt {
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: -0.05em;
  color: var(--if-ink, #161a1d);
  line-height: 1;
}
.unit {
  font-size: 0.78rem;
  color: var(--if-muted, #64748b);
  margin-left: 0.15rem;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.4rem;
}
.metric {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--if-muted, #64748b);
  padding: 0.4rem 0.5rem;
  border-radius: 0.5rem;
  background: color-mix(in srgb, var(--if-paper, #f4f1ec) 70%, var(--if-surface, #fff));
}
.metric i {
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
  width: 0.85rem;
  text-align: center;
}
.highlights {
  margin: 0.15rem 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.35rem;
  flex: 1 1 auto;
}
.highlights li {
  display: flex;
  align-items: flex-start;
  gap: 0.4rem;
  font-size: 0.78rem;
  line-height: 1.4;
  color: var(--if-muted, #64748b);
}
.highlights i {
  margin-top: 0.15rem;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
  font-size: 0.65rem;
}
.highlights strong {
  color: var(--if-ink, #161a1d);
  font-weight: 650;
}
.cta {
  margin-top: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  width: 100%;
  border: none;
  border-radius: 0.6rem;
  padding: 0.65rem 1rem;
  font-size: 0.88rem;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
  background: var(--plan-accent, var(--if-primary, #ff6c2c));
  color: #fff;
  transition: filter 0.15s ease;
  box-sizing: border-box;
}
.cta:hover {
  filter: brightness(1.06);
  color: #fff;
}
</style>
