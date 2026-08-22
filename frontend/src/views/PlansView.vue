<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { catalogApi } from '@/api'
import SiteHeader from '@/components/site/SiteHeader.vue'
import PlanFlipCard from '@/components/site/PlanFlipCard.vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { useSiteTheme } from '@/composables/useSiteTheme'
import { isPureCustomer, isStaffUser } from '@/lib/roles'
import { useAuthStore } from '@/stores/auth'
import type { ComingSoonProduct, HostingPlan } from '@/types/platform'

const router = useRouter()
const auth = useAuthStore()
const { theme, tone, load: loadTheme } = useSiteTheme()
const plans = ref<HostingPlan[]>([])
const comingSoon = ref<ComingSoonProduct[]>([])
const loading = ref(true)
const error = ref('')
const asStaff = computed(() => isStaffUser(auth.user) && !isPureCustomer(auth.user))

const featuredId = computed(() => {
  if (!plans.value.length) return ''
  const mid = plans.value.find((p) => /pro|business|growth/i.test(p.name))
  return (mid || plans.value[Math.min(1, plans.value.length - 1)]).id
})

const sortedPlans = computed(() =>
  [...plans.value].sort((a, b) => Number(a.price_monthly) - Number(b.price_monthly)),
)

onMounted(async () => {
  if (auth.isAuthenticated && !auth.user) {
    try {
      await auth.fetchUser()
    } catch {
      /* public */
    }
  }
  if (isPureCustomer(auth.user)) {
    await router.replace({ name: 'portal-account-plans' })
    return
  }
  await loadTheme()
  try {
    const { data } = await catalogApi.plans()
    plans.value = data.items
    comingSoon.value = data.coming_soon || []
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not load plans.'
  } finally {
    loading.value = false
  }
})

function choose(plan: HostingPlan) {
  localStorage.setItem('ifnotus_selected_plan', plan.id)
  router.push({ name: 'portal-signup', query: { plan: plan.slug } })
}
</script>

<template>
  <DashboardLayout v-if="asStaff">
    <div class="page staff">
      <header class="head">
        <p class="eyebrow">Public catalog</p>
        <h1>Plans customers see</h1>
        <p class="sub">
          This is the storefront. Manage prices and resources from
          <router-link :to="{ name: 'platform-plans' }">Accounts → Plans</router-link>.
        </p>
      </header>
      <p v-if="loading" class="muted">Loading plans…</p>
      <p v-else-if="error" class="err">{{ error }}</p>
      <div v-else class="grid">
        <PlanFlipCard
          v-for="plan in sortedPlans"
          :key="plan.id"
          :plan="plan"
          :featured="plan.id === featuredId"
          @choose="choose(plan)"
        />
      </div>
      <section v-if="!loading && !error && comingSoon.length" class="soon" aria-label="Coming soon">
        <h2>Coming soon</h2>
        <p class="soon-sub">Dedicated VMs need their own provisioning path — not sold on this shared node.</p>
        <div class="soon-grid">
          <article v-for="item in comingSoon" :key="item.slug" class="soon-card">
            <p class="soon-badge">Coming soon</p>
            <h3>{{ item.name }}</h3>
            <p>{{ item.blurb }}</p>
          </article>
        </div>
      </section>
    </div>
  </DashboardLayout>

  <div v-else class="page" :class="theme">
    <SiteHeader active="plans" :tone="tone" />

    <main class="wrap">
      <header class="head">
        <p class="eyebrow">Hosting</p>
        <h1>Simple plans. Clear limits.</h1>
        <p class="sub">
          Prices in GHS. Hover a card to flip it and see what’s included — resources, SSL, apps, and support.
        </p>
      </header>

      <p v-if="loading" class="muted">Loading plans…</p>
      <p v-else-if="error" class="err">{{ error }}</p>

      <div v-else class="grid">
        <PlanFlipCard
          v-for="plan in sortedPlans"
          :key="plan.id"
          :plan="plan"
          :featured="plan.id === featuredId"
          @choose="choose(plan)"
        />
      </div>

      <section v-if="!loading && !error && comingSoon.length" class="soon" aria-label="Coming soon">
        <h2>Coming soon</h2>
        <p class="soon-sub">Dedicated VMs need their own provisioning path — not sold on this shared node.</p>
        <div class="soon-grid">
          <article v-for="item in comingSoon" :key="item.slug" class="soon-card">
            <p class="soon-badge">Coming soon</p>
            <h3>{{ item.name }}</h3>
            <p>{{ item.blurb }}</p>
          </article>
        </div>
      </section>
    </main>

    <footer class="foot">
      <p>© {{ new Date().getFullYear() }} IFNOTUS</p>
      <p>
        <router-link :to="{ name: 'home' }">Home</router-link>
        ·
        <router-link :to="{ name: 'portal-signup' }">Sign up</router-link>
      </p>
    </footer>
  </div>
</template>

<style scoped>
.page.staff {
  min-height: auto;
  background: transparent;
  padding-bottom: 1.5rem;
}
.page.staff .head h1 {
  font-size: 1.4rem;
}
.page.staff .grid {
  margin-top: 1.25rem;
}
.page {
  min-height: 100vh;
  font-family: 'Figtree', 'Segoe UI', sans-serif;
  color: var(--if-ink, #12171c);
  background:
    radial-gradient(720px 360px at 12% -8%, var(--if-glow, rgba(255, 108, 44, 0.07)), transparent 60%),
    linear-gradient(180deg, var(--if-surface, #fff) 0%, var(--if-paper, #f6f7f9) 100%);
}
.page.server-dark {
  color: var(--if-ink, #f5f7fa);
  background:
    radial-gradient(720px 360px at 12% -8%, var(--if-glow, rgba(255, 108, 44, 0.14)), transparent 60%),
    linear-gradient(180deg, #12151a 0%, var(--if-paper, #0b0e12) 100%);
}
.wrap {
  max-width: 72rem;
  margin: 0 auto;
  padding: 2.75rem 1.25rem 3.5rem;
}
.head {
  max-width: 34rem;
}
.eyebrow {
  margin: 0;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--if-primary, #ff6c2c);
}
.head h1 {
  margin: 0.55rem 0 0;
  font-family: 'Sora', sans-serif;
  font-size: clamp(1.85rem, 4vw, 2.55rem);
  font-weight: 700;
  letter-spacing: -0.045em;
  line-height: 1.12;
}
.sub {
  margin: 0.7rem 0 0;
  font-size: 1.02rem;
  line-height: 1.55;
  color: var(--if-muted, #5a6570);
}
.server-dark .sub {
  color: rgba(245, 247, 250, 0.68);
}
.grid {
  margin-top: 2.25rem;
  display: grid;
  gap: 1.15rem;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
}
.soon {
  margin-top: 2.75rem;
  padding-top: 1.75rem;
  border-top: 1px solid color-mix(in srgb, var(--if-ink, #12171c) 10%, transparent);
}
.soon h2 {
  margin: 0;
  font-family: 'Sora', sans-serif;
  font-size: 1.15rem;
  letter-spacing: -0.02em;
}
.soon-sub {
  margin: 0.45rem 0 0;
  max-width: 36rem;
  font-size: 0.92rem;
  line-height: 1.5;
  color: var(--if-muted, #5a6570);
}
.soon-grid {
  margin-top: 1.1rem;
  display: grid;
  gap: 0.85rem;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
}
.soon-card {
  padding: 1.1rem 1.15rem;
  border: 1px dashed color-mix(in srgb, var(--if-ink, #12171c) 18%, transparent);
  background: color-mix(in srgb, var(--if-paper, #f6f7f9) 70%, transparent);
}
.soon-badge {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--if-muted, #5a6570);
}
.soon-card h3 {
  margin: 0.55rem 0 0;
  font-family: 'Sora', sans-serif;
  font-size: 1.05rem;
}
.soon-card p:last-child {
  margin: 0.4rem 0 0;
  font-size: 0.88rem;
  line-height: 1.45;
  color: var(--if-muted, #5a6570);
}
.muted {
  color: #7a8490;
}
.err {
  color: #b42318;
}
.foot {
  border-top: 1px solid rgba(18, 23, 28, 0.08);
  padding: 1.5rem 1.25rem 2rem;
  text-align: center;
  color: #7a8490;
  font-size: 0.8rem;
  display: grid;
  gap: 0.4rem;
}
.server-dark .foot {
  border-top-color: rgba(255, 255, 255, 0.08);
  color: rgba(245, 247, 250, 0.55);
}
.foot a {
  color: inherit;
  text-decoration: none;
}
.foot a:hover {
  color: var(--if-primary, #ff6c2c);
}
</style>
