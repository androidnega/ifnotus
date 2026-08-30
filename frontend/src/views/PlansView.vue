<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { catalogApi } from '@/api'
import SiteHeader from '@/components/site/SiteHeader.vue'
import PlanCatalogCard from '@/components/site/PlanCatalogCard.vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { useSiteTheme } from '@/composables/useSiteTheme'
import { isPureCustomer, isStaffUser } from '@/lib/roles'
import { useAuthStore } from '@/stores/auth'
import type { ComingSoonProduct, HostingPlan } from '@/types/platform'

const router = useRouter()
const auth = useAuthStore()
const { theme, tone, loaded: themeReady, load: loadTheme } = useSiteTheme()
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
</script>

<template>
  <DashboardLayout v-if="asStaff">
    <div class="plans-page staff">
      <header class="hero">
        <p class="kicker">Public catalog</p>
        <h1>Plans customers see</h1>
        <p class="lede">
          Manage prices from
          <router-link :to="{ name: 'platform-plans' }">Platform → Plans</router-link>.
        </p>
      </header>
      <p v-if="loading" class="state"><i class="fa-solid fa-spinner fa-spin" aria-hidden="true" /> Loading…</p>
      <p v-else-if="error" class="state err">{{ error }}</p>
      <div v-else class="plan-grid">
        <PlanCatalogCard
          v-for="plan in sortedPlans"
          :key="plan.id"
          :plan="plan"
          :featured="plan.id === featuredId"
        />
      </div>
    </div>
  </DashboardLayout>

  <div v-else class="plans-page" :class="[theme, { ready: themeReady }]">
    <SiteHeader active="plans" :tone="tone" surface="solid" />

    <header class="hero-band">
      <div class="inset">
        <p class="kicker"><i class="fa-solid fa-layer-group" aria-hidden="true" /> Hosting</p>
        <h1>Pick a plan. Go live.</h1>
        <p class="lede">
          Prices in GHS. Every plan includes SSL, mail, backups, FTP/SFTP, and an AI engineer —
          sign up with your phone and we provision in minutes.
        </p>
        <ul class="trust" aria-label="Included on every plan">
          <li><i class="fa-solid fa-lock" aria-hidden="true" /> SSL</li>
          <li><i class="fa-solid fa-envelope" aria-hidden="true" /> Mail</li>
          <li><i class="fa-solid fa-shield-halved" aria-hidden="true" /> Backups</li>
          <li><i class="fa-solid fa-robot" aria-hidden="true" /> AI credits</li>
        </ul>
      </div>
    </header>

    <main class="body">
      <div class="inset">
        <p v-if="loading" class="state">
          <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" /> Loading plans…
        </p>
        <p v-else-if="error" class="state err">{{ error }}</p>

        <div v-else class="plan-grid">
          <PlanCatalogCard
            v-for="plan in sortedPlans"
            :key="plan.id"
            :plan="plan"
            :featured="plan.id === featuredId"
          />
        </div>

        <section v-if="!loading && !error && comingSoon.length" class="soon">
          <h2><i class="fa-regular fa-clock" aria-hidden="true" /> Coming soon</h2>
          <p class="soon-lede">Dedicated VPS products — separate provisioning, not on shared hosting yet.</p>
          <div class="soon-grid">
            <article v-for="item in comingSoon" :key="item.slug" class="soon-card">
              <h3>{{ item.name }}</h3>
              <p>{{ item.blurb }}</p>
            </article>
          </div>
        </section>
      </div>
    </main>

    <footer class="foot">
      <router-link :to="{ name: 'home' }">Home</router-link>
      <span aria-hidden="true">·</span>
      <router-link :to="{ name: 'contact' }">Contact</router-link>
      <span aria-hidden="true">·</span>
      <router-link :to="{ name: 'portal-signup' }">Sign up</router-link>
    </footer>
  </div>
</template>

<style scoped>
.plans-page {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  font-family: 'Figtree', 'Segoe UI', sans-serif;
  color: var(--if-ink, #161a1d);
  background: var(--if-paper, #f8fafc);
  opacity: 0;
  transition: opacity 0.2s ease;
}
.plans-page.ready {
  opacity: 1;
}
.plans-page.staff {
  opacity: 1;
  min-height: auto;
  background: transparent;
  padding-bottom: 1.5rem;
}

.hero-band {
  flex-shrink: 0;
  background: color-mix(in srgb, var(--if-primary, #ff6c2c) 6%, var(--if-surface, #fff));
  border-bottom: 1px solid var(--if-border, #e7e2db);
  padding: 1.35rem 0 1.5rem;
}
.inset {
  max-width: 76rem;
  margin: 0 auto;
  padding-inline: clamp(1.15rem, 3vw, 2rem);
  box-sizing: border-box;
  width: 100%;
}
.kicker {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--if-primary, #ff6c2c);
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
.hero-band h1,
.hero h1 {
  margin: 0.45rem 0 0;
  font-family: 'Sora', sans-serif;
  font-size: clamp(1.75rem, 4vw, 2.5rem);
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1.08;
}
.lede {
  margin: 0.65rem 0 0;
  max-width: 40rem;
  font-size: clamp(0.92rem, 1.8vw, 1.02rem);
  line-height: 1.55;
  color: var(--if-muted, #64748b);
}
.lede a {
  color: var(--if-primary, #ff6c2c);
  font-weight: 650;
  text-decoration: none;
}
.lede a:hover {
  text-decoration: underline;
}
.trust {
  margin: 1rem 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.85rem;
}
.trust li {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--if-ink, #161a1d);
  padding: 0.35rem 0.65rem;
  border-radius: 999px;
  background: var(--if-surface, #fff);
  border: 1px solid var(--if-border, #e7e2db);
}
.trust i {
  color: var(--if-primary, #ff6c2c);
}

.body {
  flex: 1 1 auto;
  padding: 1.35rem 0 1.75rem;
}
.hero {
  margin-bottom: 1.25rem;
}

.state {
  margin: 0;
  padding: 2rem 0;
  text-align: center;
  color: var(--if-muted, #64748b);
  font-size: 0.9rem;
}
.state i {
  margin-right: 0.35rem;
}
.state.err {
  color: #b42318;
}

.plan-grid {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fill, minmax(16.5rem, 1fr));
  align-items: stretch;
}
@media (min-width: 1100px) {
  .plan-grid {
    grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr));
    gap: 1.15rem;
  }
}

.soon {
  margin-top: 2.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--if-border, #e7e2db);
}
.soon h2 {
  margin: 0;
  font-family: 'Sora', sans-serif;
  font-size: 1.05rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
.soon-lede {
  margin: 0.4rem 0 0;
  font-size: 0.88rem;
  color: var(--if-muted, #64748b);
  max-width: 36rem;
}
.soon-grid {
  margin-top: 0.85rem;
  display: grid;
  gap: 0.65rem;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
}
.soon-card {
  padding: 0.85rem 1rem;
  border: 1px dashed var(--if-border, #d5dbe3);
  border-radius: 0.75rem;
  background: var(--if-surface, #fff);
}
.soon-card h3 {
  margin: 0;
  font-size: 0.92rem;
  font-weight: 700;
}
.soon-card p {
  margin: 0.35rem 0 0;
  font-size: 0.8rem;
  line-height: 1.45;
  color: var(--if-muted, #64748b);
}

.foot {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.5rem 0.65rem;
  padding: 0.75rem clamp(1.15rem, 3vw, 2rem) 1rem;
  font-size: 0.72rem;
  color: var(--if-muted, #64748b);
  border-top: 1px solid var(--if-border, #e7e2db);
  background: var(--if-surface, #fff);
}
.foot a {
  color: inherit;
  text-decoration: none;
  font-weight: 600;
}
.foot a:hover {
  color: var(--if-primary, #ff6c2c);
}
</style>
