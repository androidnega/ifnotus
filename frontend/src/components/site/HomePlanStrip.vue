<script setup lang="ts">
import { computed } from 'vue'
import type { HostingPlan } from '@/types/platform'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { planAccentFromPrice, softAccent } from '@/lib/theme'
import { useSiteTheme } from '@/composables/useSiteTheme'

const props = defineProps<{
  plans: HostingPlan[]
  featuredId?: string
  loading?: boolean
}>()

const emit = defineEmits<{
  choose: [plan: HostingPlan]
}>()

const { planColors } = useSiteTheme()

const sorted = computed(() =>
  [...props.plans].sort((a, b) => Number(a.price_monthly) - Number(b.price_monthly)),
)

function cardStyle(plan: HostingPlan) {
  const accent = planAccentFromPrice(Number(plan.price_monthly), planColors.value, plan.features)
  return {
    '--plan-accent': accent,
    '--plan-accent-soft': softAccent(accent, 0.14),
  }
}

function price(plan: HostingPlan) {
  const n = Number(plan.price_monthly)
  return Number.isInteger(n) ? String(n) : String(n)
}
</script>

<template>
  <section class="strip" aria-label="Hosting plans">
    <div class="strip-head">
      <p class="strip-kicker"><i class="fa-solid fa-layer-group" aria-hidden="true" /> Hosting plans</p>
      <router-link class="strip-all" :to="{ name: 'plans' }">
        Compare all <i class="fa-solid fa-arrow-right" aria-hidden="true" />
      </router-link>
    </div>

    <p v-if="loading" class="strip-loading">
      <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" /> Loading plans…
    </p>

    <div v-else class="strip-track" role="list">
      <article
        v-for="plan in sorted"
        :key="plan.id"
        class="plan-tile"
        :class="{ featured: plan.id === featuredId }"
        :style="cardStyle(plan)"
        role="listitem"
      >
        <div class="tile-top">
          <h3>{{ plan.name }}</h3>
          <span v-if="plan.id === featuredId" class="tile-badge">Popular</span>
        </div>
        <p class="tile-price">
          <span class="cur">₵</span>{{ price(plan) }}<span class="unit">/mo</span>
        </p>
        <ul class="tile-specs">
          <li><i class="fa-solid fa-microchip" aria-hidden="true" /> {{ formatCpu(plan.cpu_cores) }} vCPU</li>
          <li><i class="fa-solid fa-memory" aria-hidden="true" /> {{ formatRamGb(plan.ram_gb) }}</li>
          <li><i class="fa-solid fa-hard-drive" aria-hidden="true" /> {{ plan.storage_gb }} GB</li>
        </ul>
        <button type="button" class="tile-cta" @click="emit('choose', plan)">
          Choose {{ plan.name }}
        </button>
      </article>
    </div>
  </section>
</template>

<style scoped>
.strip {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  min-width: 0;
}
.strip-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0 0.15rem;
}
.strip-kicker {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--if-muted, #64748b);
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
.strip-all {
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--if-primary, #ff6c2c);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  white-space: nowrap;
}
.strip-loading {
  margin: 0;
  font-size: 0.85rem;
  color: var(--if-muted, #64748b);
}
.strip-track {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(11.5rem, 1fr);
  gap: 0.65rem;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scroll-snap-type: x mandatory;
  padding-bottom: 0.15rem;
  -webkit-overflow-scrolling: touch;
}
@media (min-width: 900px) {
  .strip-track {
    grid-auto-flow: unset;
    grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
    overflow-x: visible;
  }
}
.plan-tile {
  scroll-snap-align: start;
  border: 1px solid var(--if-border, #e7e2db);
  border-radius: 0.85rem;
  background: var(--if-surface, #fff);
  padding: 0.75rem 0.8rem 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 0;
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.04);
  border-top: 3px solid var(--plan-accent, var(--if-primary, #ff6c2c));
}
.plan-tile.featured {
  background: linear-gradient(180deg, var(--plan-accent-soft, rgba(255, 108, 44, 0.1)) 0%, var(--if-surface, #fff) 55%);
}
.tile-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem;
}
.tile-top h3 {
  margin: 0;
  font-family: 'Sora', sans-serif;
  font-size: 0.88rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--if-ink, #161a1d);
}
.tile-badge {
  font-size: 0.58rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
  background: var(--plan-accent-soft, rgba(255, 108, 44, 0.12));
  border-radius: 999px;
  padding: 0.15rem 0.45rem;
}
.tile-price {
  margin: 0;
  font-family: 'Sora', sans-serif;
  font-size: 1.35rem;
  font-weight: 800;
  letter-spacing: -0.04em;
  color: var(--if-ink, #161a1d);
  line-height: 1;
}
.tile-price .cur {
  font-size: 0.85rem;
  margin-right: 0.1rem;
  opacity: 0.75;
}
.tile-price .unit {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--if-muted, #64748b);
  margin-left: 0.15rem;
}
.tile-specs {
  margin: 0.15rem 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.2rem;
  font-size: 0.68rem;
  color: var(--if-muted, #64748b);
}
.tile-specs li {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.tile-specs i {
  width: 0.85rem;
  text-align: center;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
  opacity: 0.85;
}
.tile-cta {
  margin-top: auto;
  border: none;
  border-radius: 0.55rem;
  padding: 0.45rem 0.65rem;
  font-size: 0.75rem;
  font-weight: 700;
  cursor: pointer;
  background: var(--plan-accent, var(--if-primary, #ff6c2c));
  color: #fff;
  transition: filter 0.15s ease;
}
.tile-cta:hover {
  filter: brightness(1.06);
}
</style>
