<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { catalogApi } from '@/api'
import PortalShell from '@/components/portal/PortalShell.vue'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import type { HostingPlan } from '@/types/platform'

const router = useRouter()
const plans = ref<HostingPlan[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const { data } = await catalogApi.plans()
    plans.value = data.items
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not load plans.'
  } finally {
    loading.value = false
  }
})

const featuredId = computed(() => {
  if (!plans.value.length) return ''
  const mid = plans.value.find((p) => /pro|growth|business/i.test(p.name))
  return (mid || plans.value[Math.min(1, plans.value.length - 1)]).id
})

function choose(plan: HostingPlan) {
  localStorage.setItem('ifnotus_selected_plan', plan.id)
  router.push({ name: 'portal-signup', query: { plan: plan.slug } })
}

function goSignup() {
  router.push({ name: 'portal-signup' })
}
</script>

<template>
  <PortalShell mode="marketing">
    <template #actions>
      <router-link class="portal-link" :to="{ name: 'login' }">Log in</router-link>
      <button type="button" class="portal-cta" @click="goSignup">Get started</button>
    </template>

    <!-- First viewport: brand + one promise + one CTA -->
    <section class="hero">
      <p class="hero-brand">IFNOTUS</p>
      <h1 class="hero-title">Your site. Our stack.</h1>
      <p class="hero-copy">
        Pick a plan, pay the invoice, and your site goes live with files, DNS, and SSL. Install WordPress or Laravel when you need a database.
      </p>
      <div class="hero-actions">
        <a href="#plans" class="portal-cta portal-cta-lg">See plans</a>
        <router-link class="portal-link-quiet" :to="{ name: 'login' }">I already have an account</router-link>
      </div>
    </section>

    <section id="plans" class="plans">
      <div class="plans-head">
        <h2>Plans</h2>
        <p>Monthly pricing in GHS. Upgrade or renew anytime from your panel.</p>
      </div>

      <p v-if="loading" class="muted">Loading plans…</p>
      <p v-else-if="error" class="err">{{ error }}</p>

      <div v-else class="plans-grid">
        <article
          v-for="plan in plans"
          :key="plan.id"
          class="plan"
          :class="{ featured: plan.id === featuredId }"
        >
          <header>
            <h3>{{ plan.name }}</h3>
            <p class="price">
              <span class="amount">{{ plan.price_monthly }}</span>
              <span class="unit">GHS / mo</span>
            </p>
          </header>
          <ul>
            <li>{{ formatCpu(plan.cpu_cores) }} vCPU</li>
            <li>{{ formatRamGb(plan.ram_gb) }} RAM</li>
            <li>{{ plan.storage_gb }} GB storage</li>
            <li>{{ plan.bandwidth_tb }} TB bandwidth</li>
            <li>{{ plan.ai_credits }} AI credits</li>
          </ul>
          <button type="button" class="plan-btn" @click="choose(plan)">
            Choose {{ plan.name }}
          </button>
        </article>
      </div>
    </section>
  </PortalShell>
</template>

<style scoped>
.portal-link {
  padding: 0.4rem 0.75rem;
  color: #5c6670;
  text-decoration: none;
}
.portal-link:hover {
  color: var(--if-primary, #ff6c2c);
}
.portal-link-quiet {
  font-size: 0.9rem;
  color: #5c6670;
  text-decoration: none;
}
.portal-link-quiet:hover {
  color: #1a1f24;
}
.portal-cta {
  border-radius: 0.5rem;
  background: var(--if-primary, #ff6c2c);
  padding: 0.5rem 1rem;
  font-weight: 600;
  color: #fff;
  border: none;
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
}
.portal-cta:hover {
  background: var(--if-primary-hover, #e85f22);
}
.portal-cta-lg {
  padding: 0.85rem 1.4rem;
  font-size: 1rem;
}

.hero {
  min-height: min(72vh, 38rem);
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 3.5rem 0 2.5rem;
  max-width: 40rem;
  position: relative;
}
.hero::before {
  content: '';
  position: absolute;
  inset: 10% -8% auto auto;
  width: min(42vw, 18rem);
  height: min(42vw, 18rem);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 108, 44, 0.18), transparent 70%);
  pointer-events: none;
  animation: drift 12s ease-in-out infinite alternate;
}
.hero-brand {
  font-family: Syne, sans-serif;
  font-size: clamp(2.8rem, 8vw, 4.5rem);
  font-weight: 800;
  letter-spacing: -0.05em;
  line-height: 0.95;
  color: var(--if-primary, #ff6c2c);
  margin: 0;
  animation: rise 0.7s ease-out both;
}
.hero-title {
  margin: 1rem 0 0;
  font-family: Syne, sans-serif;
  font-size: clamp(1.6rem, 4vw, 2.25rem);
  font-weight: 700;
  letter-spacing: -0.03em;
  color: #1a1f24;
  animation: rise 0.7s ease-out 0.08s both;
}
.hero-copy {
  margin: 1rem 0 0;
  font-size: 1.05rem;
  line-height: 1.55;
  color: #5c6670;
  max-width: 34rem;
  animation: rise 0.7s ease-out 0.16s both;
}
.hero-actions {
  margin-top: 1.75rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  animation: rise 0.7s ease-out 0.24s both;
}
@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes drift {
  from {
    transform: translate(0, 0);
  }
  to {
    transform: translate(-1.5rem, 1rem);
  }
}

.plans {
  padding: 3rem 0 1rem;
  border-top: 1px solid rgba(26, 31, 36, 0.08);
}
.plans-head h2 {
  font-family: Syne, sans-serif;
  font-size: 1.5rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 0;
}
.plans-head p {
  margin: 0.4rem 0 0;
  color: #5c6670;
  font-size: 0.95rem;
}
.plans-grid {
  margin-top: 1.75rem;
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}
.plan {
  background: #fff;
  border: 1px solid #e4e8ec;
  border-radius: 0.85rem;
  padding: 1.25rem 1.2rem 1.2rem;
  display: flex;
  flex-direction: column;
}
.plan.featured {
  border-color: var(--if-primary, #ff6c2c);
  box-shadow: 0 0 0 1px rgba(255, 108, 44, 0.25);
}
.plan h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
}
.price {
  margin: 0.65rem 0 0;
  display: flex;
  align-items: baseline;
  gap: 0.35rem;
}
.amount {
  font-family: Syne, sans-serif;
  font-size: 1.85rem;
  font-weight: 700;
  color: var(--if-primary, #ff6c2c);
  letter-spacing: -0.03em;
}
.unit {
  font-size: 0.8rem;
  color: #7a8490;
}
.plan ul {
  margin: 1rem 0 0;
  padding: 0;
  list-style: none;
  flex: 1;
  font-size: 0.9rem;
  color: #5c6670;
  line-height: 1.7;
}
.plan-btn {
  margin-top: 1.1rem;
  width: 100%;
  border: none;
  border-radius: 0.5rem;
  background: #1a1f24;
  color: #fff;
  font-weight: 600;
  font-size: 0.875rem;
  padding: 0.7rem;
  cursor: pointer;
}
.plan.featured .plan-btn {
  background: var(--if-primary, #ff6c2c);
}
.plan-btn:hover {
  filter: brightness(1.08);
}
.muted {
  color: #7a8490;
  font-size: 0.9rem;
}
.err {
  color: #b91c1c;
  font-size: 0.9rem;
}
</style>
