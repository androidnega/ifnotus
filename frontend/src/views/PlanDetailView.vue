<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { catalogApi } from '@/api'
import SiteHeader from '@/components/site/SiteHeader.vue'
import { useSiteTheme } from '@/composables/useSiteTheme'
import { isPureCustomer } from '@/lib/roles'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { packItems } from '@/lib/planPack'
import { packStacksForDisplay, sshHeadline } from '@/lib/planMatrix'
import { planAccentFromPrice, softAccent } from '@/lib/theme'
import { useAuthStore } from '@/stores/auth'
import type { HostingPlan } from '@/types/platform'

type SectionId = 'overview' | 'included' | 'stacks' | 'notes' | 'billing'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { theme, tone, loaded: themeReady, planColors, load: loadTheme } = useSiteTheme()

const plan = ref<HostingPlan | null>(null)
const siblings = ref<HostingPlan[]>([])
const loading = ref(true)
const error = ref('')
const openSection = ref<SectionId>('overview')
const billingTerms = ref<
  Array<{
    months: number
    label: string
    recommended?: boolean
    discount_pct?: number
    plan_total?: number | null
  }>
>([])
const billingLoaded = ref(false)
const billingLoading = ref(false)

const slug = computed(() => String(route.params.slug || ''))

const accent = computed(() =>
  plan.value
    ? planAccentFromPrice(Number(plan.value.price_monthly), planColors.value, plan.value.features)
    : '#ff6c2c',
)

const pageStyle = computed(() => ({
  '--plan-accent': accent.value,
  '--plan-accent-soft': softAccent(accent.value, 0.12),
}))

const highlights = computed(() => (plan.value ? packItems(plan.value) : []))
const detailHighlights = computed(() =>
  highlights.value.filter((item) => !['cpu', 'ram', 'disk'].includes(item.id)),
)

const stacks = computed(() => (plan.value ? packStacksForDisplay(plan.value) : []))
const productionNotes = computed(() => plan.value?.catalog_card?.production_notes ?? [])
const blurb = computed(() => plan.value?.catalog_card?.blurb || '')

const sections = computed(() => {
  const rows: Array<{ id: SectionId; label: string; icon: string; count?: number }> = [
    { id: 'overview', label: 'Overview', icon: 'fa-circle-info' },
    { id: 'included', label: "What's included", icon: 'fa-list-check', count: detailHighlights.value.length },
    { id: 'stacks', label: 'Technology stacks', icon: 'fa-layer-group', count: stacks.value.length },
  ]
  if (productionNotes.value.length) {
    rows.push({ id: 'notes', label: 'Good to know', icon: 'fa-shield-halved', count: productionNotes.value.length })
  }
  rows.push({ id: 'billing', label: 'Billing options', icon: 'fa-calendar-check' })
  return rows
})

function priceLabel(value: number) {
  return Number.isInteger(value) ? String(value) : String(value)
}

function toggleSection(id: SectionId) {
  openSection.value = openSection.value === id ? 'overview' : id
  if (id === 'billing' && !billingLoaded.value && plan.value) {
    void loadBillingTerms()
  }
}

async function loadBillingTerms() {
  if (!plan.value || billingLoading.value) return
  billingLoading.value = true
  try {
    const { data } = await catalogApi.billingTerms(Number(plan.value.price_monthly))
    billingTerms.value = data.terms || []
    billingLoaded.value = true
  } catch {
    billingTerms.value = []
    billingLoaded.value = true
  } finally {
    billingLoading.value = false
  }
}

async function loadPlan() {
  loading.value = true
  error.value = ''
  plan.value = null
  billingTerms.value = []
  billingLoaded.value = false
  openSection.value = 'overview'

  try {
    const [detailRes, listRes] = await Promise.all([
      catalogApi.plan(slug.value),
      catalogApi.plans(),
    ])
    plan.value = detailRes.data
    siblings.value = (listRes.data.items || []).filter((p) => p.slug !== detailRes.data.slug)
  } catch (e: unknown) {
    const err = e as { response?: { status?: number; data?: { error?: { message?: string } } } }
    error.value =
      err.response?.status === 404
        ? 'This plan is not available.'
        : err.response?.data?.error?.message ?? 'Could not load plan details.'
  } finally {
    loading.value = false
  }
}

function choose() {
  if (!plan.value) return
  localStorage.setItem('ifnotus_selected_plan', plan.value.id)
  router.push({ name: 'portal-signup', query: { plan: plan.value.slug } })
}

function stackLevelLabel(level: string) {
  if (level === 'yes') return 'Included'
  if (level === 'limited') return 'Limited'
  return 'Not included'
}

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
  await loadPlan()
})

watch(slug, () => {
  if (themeReady.value) void loadPlan()
})
</script>

<template>
  <div class="plan-detail" :class="[theme, { ready: themeReady }]" :style="pageStyle">
    <SiteHeader active="plans" :tone="tone" surface="solid" />

    <header class="hero">
      <div class="inset">
        <router-link :to="{ name: 'plans' }" class="back">
          <i class="fa-solid fa-arrow-left" aria-hidden="true" />
          All plans
        </router-link>

        <p v-if="loading" class="state">
          <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" /> Loading plan…
        </p>

        <template v-else-if="plan">
          <div class="hero-grid">
            <div class="hero-copy">
              <p class="kicker"><i class="fa-solid fa-box-open" aria-hidden="true" /> Hosting plan</p>
              <h1>{{ plan.name }}</h1>
              <p class="ssh">{{ sshHeadline(plan) }}</p>
              <p v-if="blurb" class="lede">{{ blurb }}</p>
            </div>

            <aside class="summary" aria-label="Plan summary">
              <p class="price">
                <span class="cur">₵</span>
                <span class="amt">{{ priceLabel(Number(plan.price_monthly)) }}</span>
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
                  <span>{{ plan.ai_credits }} AI credits</span>
                </div>
              </div>
              <button type="button" class="cta" @click="choose">
                Get {{ plan.name }}
                <i class="fa-solid fa-arrow-right" aria-hidden="true" />
              </button>
            </aside>
          </div>
        </template>

        <p v-else-if="error" class="state err">
          {{ error }}
          <router-link :to="{ name: 'plans' }">Back to plans</router-link>
        </p>
      </div>
    </header>

    <main v-if="plan" class="body">
      <div class="inset detail-grid">
        <nav class="section-nav" aria-label="Plan sections">
          <button
            v-for="section in sections"
            :key="section.id"
            type="button"
            class="nav-item"
            :class="{ open: openSection === section.id }"
            :aria-expanded="openSection === section.id"
            @click="toggleSection(section.id)"
          >
            <i class="fa-solid" :class="section.icon" aria-hidden="true" />
            <span class="nav-label">{{ section.label }}</span>
            <span v-if="section.count != null" class="nav-count">{{ section.count }}</span>
            <i
              class="fa-solid chev"
              :class="openSection === section.id ? 'fa-chevron-up' : 'fa-chevron-down'"
              aria-hidden="true"
            />
          </button>
        </nav>

        <div class="panels">
          <section v-show="openSection === 'overview'" class="panel">
            <h2>Overview</h2>
            <p v-if="blurb" class="panel-lede">{{ blurb }}</p>
            <p v-else class="panel-lede muted">
              {{ plan.name }} is a shared hosting plan on IFNOTUS with SSL, mail, backups, and panel tools included.
            </p>
            <ul class="quick-stats">
              <li>
                <strong>Bandwidth</strong>
                <span>{{ plan.bandwidth_tb }} TB / month</span>
              </li>
              <li>
                <strong>SSH access</strong>
                <span>{{ sshHeadline(plan) }}</span>
              </li>
              <li v-if="plan.catalog_card?.domains != null">
                <strong>Custom domains</strong>
                <span>{{ plan.catalog_card.domains >= 999 ? 'Unlimited*' : plan.catalog_card.domains }}</span>
              </li>
            </ul>
          </section>

          <section v-show="openSection === 'included'" class="panel">
            <h2>What's included</h2>
            <ul class="feature-list">
              <li v-for="item in detailHighlights" :key="item.id">
                <i class="fa-solid fa-check" aria-hidden="true" />
                <div>
                  <strong>{{ item.label }}</strong>
                  <p>{{ item.detail }}</p>
                </div>
              </li>
            </ul>
          </section>

          <section v-show="openSection === 'stacks'" class="panel">
            <h2>Technology stacks</h2>
            <p class="panel-lede muted">What's available on this plan — included stacks are ready to deploy.</p>
            <div class="stack-grid">
              <article
                v-for="stack in stacks"
                :key="stack.id"
                class="stack-card"
                :class="stack.level"
              >
                <span class="stack-name">{{ stack.label }}</span>
                <span class="stack-badge">{{ stackLevelLabel(stack.level) }}</span>
              </article>
            </div>
          </section>

          <section v-if="productionNotes.length" v-show="openSection === 'notes'" class="panel">
            <h2>Good to know</h2>
            <ul class="notes-list">
              <li v-for="(note, idx) in productionNotes" :key="idx">
                <i class="fa-solid fa-circle-info" aria-hidden="true" />
                <span>{{ note }}</span>
              </li>
            </ul>
          </section>

          <section v-show="openSection === 'billing'" class="panel">
            <h2>Billing options</h2>
            <p class="panel-lede muted">Choose a term at checkout — longer terms may include a discount.</p>
            <p v-if="billingLoading" class="state inline">
              <i class="fa-solid fa-spinner fa-spin" aria-hidden="true" /> Loading terms…
            </p>
            <ul v-else-if="billingTerms.length" class="billing-list">
              <li v-for="term in billingTerms" :key="term.months" :class="{ recommended: term.recommended }">
                <div>
                  <strong>{{ term.label }}</strong>
                  <span v-if="term.recommended" class="rec-badge">Recommended</span>
                </div>
                <span v-if="term.plan_total != null" class="billing-amt">₵{{ term.plan_total }}</span>
                <span v-if="term.discount_pct" class="billing-disc">Save {{ term.discount_pct }}%</span>
              </li>
            </ul>
            <p v-else class="panel-lede muted">Monthly billing available at signup.</p>
          </section>
        </div>
      </div>

      <div v-if="siblings.length" class="inset related">
        <h2>Compare other plans</h2>
        <div class="related-grid">
          <router-link
            v-for="other in siblings"
            :key="other.id"
            :to="{ name: 'plan-detail', params: { slug: other.slug } }"
            class="related-card"
          >
            <span class="related-name">{{ other.name }}</span>
            <span class="related-price">₵{{ priceLabel(Number(other.price_monthly)) }}/mo</span>
            <span class="related-more">View plan <i class="fa-solid fa-arrow-right" aria-hidden="true" /></span>
          </router-link>
        </div>
      </div>
    </main>

    <footer class="foot">
      <router-link :to="{ name: 'plans' }">All plans</router-link>
      <span aria-hidden="true">·</span>
      <router-link :to="{ name: 'home' }">Home</router-link>
      <span aria-hidden="true">·</span>
      <router-link :to="{ name: 'portal-signup' }">Sign up</router-link>
    </footer>
  </div>
</template>

<style scoped>
.plan-detail {
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
.plan-detail.ready {
  opacity: 1;
}
.inset {
  max-width: 76rem;
  margin: 0 auto;
  padding-inline: clamp(1.15rem, 3vw, 2rem);
  box-sizing: border-box;
  width: 100%;
}

.hero {
  flex-shrink: 0;
  background: color-mix(in srgb, var(--plan-accent, var(--if-primary, #ff6c2c)) 7%, var(--if-surface, #fff));
  border-bottom: 1px solid var(--if-border, #e7e2db);
  padding: 1rem 0 1.35rem;
}
.back {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--if-muted, #64748b);
  text-decoration: none;
  margin-bottom: 0.85rem;
}
.back:hover {
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
}
.kicker {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
.hero-grid {
  display: grid;
  gap: 1.25rem;
  align-items: start;
}
@media (min-width: 900px) {
  .hero-grid {
    grid-template-columns: 1fr minmax(15rem, 20rem);
    gap: 1.75rem;
  }
}
.hero-copy h1 {
  margin: 0.4rem 0 0;
  font-family: 'Sora', sans-serif;
  font-size: clamp(1.85rem, 4vw, 2.65rem);
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1.06;
}
.ssh {
  margin: 0.35rem 0 0;
  font-size: 0.82rem;
  font-weight: 650;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
}
.lede {
  margin: 0.65rem 0 0;
  max-width: 38rem;
  font-size: 0.95rem;
  line-height: 1.55;
  color: var(--if-muted, #64748b);
}

.summary {
  padding: 1rem 1.05rem;
  border-radius: 1rem;
  border: 1px solid var(--if-border, #e7e2db);
  background: var(--if-surface, #fff);
  box-shadow: 0 4px 18px rgb(15 23 42 / 0.06);
  border-top: 3px solid var(--plan-accent, var(--if-primary, #ff6c2c));
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
  font-size: 2.1rem;
  font-weight: 800;
  letter-spacing: -0.05em;
  line-height: 1;
}
.unit {
  font-size: 0.78rem;
  color: var(--if-muted, #64748b);
  margin-left: 0.15rem;
}
.metrics {
  margin-top: 0.75rem;
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
  background: color-mix(in srgb, var(--if-paper, #f8fafc) 70%, var(--if-surface, #fff));
}
.metric i {
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
  width: 0.85rem;
  text-align: center;
}
.cta {
  margin-top: 0.85rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  width: 100%;
  border: none;
  border-radius: 0.6rem;
  padding: 0.7rem 1rem;
  font-size: 0.9rem;
  font-weight: 700;
  cursor: pointer;
  background: var(--plan-accent, var(--if-primary, #ff6c2c));
  color: #fff;
  transition: filter 0.15s ease;
}
.cta:hover {
  filter: brightness(1.06);
}

.body {
  flex: 1 1 auto;
  padding: 1.35rem 0 1.75rem;
}
.detail-grid {
  display: grid;
  gap: 1rem;
}
@media (min-width: 900px) {
  .detail-grid {
    grid-template-columns: minmax(14rem, 18rem) 1fr;
    gap: 1.25rem;
    align-items: start;
  }
}

.section-nav {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
@media (max-width: 899px) {
  .section-nav {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
  }
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  width: 100%;
  border: 1px solid var(--if-border, #e7e2db);
  border-radius: 0.65rem;
  padding: 0.65rem 0.75rem;
  background: var(--if-surface, #fff);
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: var(--if-ink, #161a1d);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.nav-item:hover {
  border-color: color-mix(in srgb, var(--plan-accent, var(--if-primary, #ff6c2c)) 40%, var(--if-border, #e7e2db));
}
.nav-item.open {
  border-color: var(--plan-accent, var(--if-primary, #ff6c2c));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--plan-accent, var(--if-primary, #ff6c2c)) 25%, transparent);
  background: var(--plan-accent-soft, rgba(255, 108, 44, 0.08));
}
.nav-item > i:first-child {
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
  width: 1rem;
  text-align: center;
}
.nav-label {
  flex: 1 1 auto;
  font-size: 0.82rem;
  font-weight: 650;
}
.nav-count {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--if-muted, #64748b);
  background: var(--if-paper, #f8fafc);
  border-radius: 999px;
  padding: 0.1rem 0.4rem;
}
.chev {
  font-size: 0.65rem;
  color: var(--if-muted, #64748b);
}

.panel {
  padding: 1.1rem 1.15rem;
  border: 1px solid var(--if-border, #e7e2db);
  border-radius: 1rem;
  background: var(--if-surface, #fff);
  min-height: 12rem;
}
.panel h2 {
  margin: 0;
  font-family: 'Sora', sans-serif;
  font-size: 1.05rem;
  font-weight: 700;
}
.panel-lede {
  margin: 0.55rem 0 0;
  font-size: 0.88rem;
  line-height: 1.5;
  color: var(--if-ink, #161a1d);
}
.panel-lede.muted {
  color: var(--if-muted, #64748b);
}

.quick-stats {
  margin: 0.85rem 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.5rem;
}
.quick-stats li {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  font-size: 0.84rem;
  padding: 0.55rem 0.65rem;
  border-radius: 0.55rem;
  background: color-mix(in srgb, var(--if-paper, #f8fafc) 65%, var(--if-surface, #fff));
}
.quick-stats strong {
  font-weight: 650;
}

.feature-list {
  margin: 0.75rem 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.55rem;
}
.feature-list li {
  display: flex;
  gap: 0.55rem;
  align-items: flex-start;
  padding: 0.55rem 0.65rem;
  border-radius: 0.55rem;
  background: color-mix(in srgb, var(--if-paper, #f8fafc) 55%, var(--if-surface, #fff));
}
.feature-list i {
  margin-top: 0.2rem;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
  font-size: 0.7rem;
}
.feature-list strong {
  display: block;
  font-size: 0.84rem;
  font-weight: 650;
}
.feature-list p {
  margin: 0.15rem 0 0;
  font-size: 0.8rem;
  line-height: 1.45;
  color: var(--if-muted, #64748b);
}

.stack-grid {
  margin-top: 0.75rem;
  display: grid;
  gap: 0.45rem;
  grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr));
}
.stack-card {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.55rem 0.65rem;
  border-radius: 0.55rem;
  border: 1px solid var(--if-border, #e7e2db);
  background: var(--if-surface, #fff);
}
.stack-card.yes {
  border-color: color-mix(in srgb, var(--plan-accent, #22c55e) 35%, var(--if-border, #e7e2db));
}
.stack-card.limited {
  opacity: 0.85;
}
.stack-name {
  font-size: 0.8rem;
  font-weight: 650;
}
.stack-badge {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--if-muted, #64748b);
}
.stack-card.yes .stack-badge {
  color: #15803d;
}

.notes-list {
  margin: 0.75rem 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.5rem;
}
.notes-list li {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
  font-size: 0.84rem;
  line-height: 1.45;
  color: var(--if-muted, #64748b);
  padding: 0.55rem 0.65rem;
  border-radius: 0.55rem;
  background: color-mix(in srgb, var(--if-paper, #f8fafc) 55%, var(--if-surface, #fff));
}
.notes-list i {
  margin-top: 0.15rem;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
}

.billing-list {
  margin: 0.75rem 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.45rem;
}
.billing-list li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.75rem;
  justify-content: space-between;
  padding: 0.6rem 0.7rem;
  border-radius: 0.55rem;
  border: 1px solid var(--if-border, #e7e2db);
}
.billing-list li.recommended {
  border-color: var(--plan-accent, var(--if-primary, #ff6c2c));
  background: var(--plan-accent-soft, rgba(255, 108, 44, 0.08));
}
.rec-badge {
  margin-left: 0.35rem;
  font-size: 0.62rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
}
.billing-amt {
  font-weight: 700;
  font-family: 'Sora', sans-serif;
}
.billing-disc {
  font-size: 0.75rem;
  color: #15803d;
  font-weight: 650;
}

.related {
  margin-top: 1.75rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--if-border, #e7e2db);
}
.related h2 {
  margin: 0;
  font-family: 'Sora', sans-serif;
  font-size: 1rem;
  font-weight: 700;
}
.related-grid {
  margin-top: 0.75rem;
  display: grid;
  gap: 0.55rem;
  grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr));
}
.related-card {
  display: grid;
  gap: 0.2rem;
  padding: 0.75rem 0.85rem;
  border-radius: 0.65rem;
  border: 1px solid var(--if-border, #e7e2db);
  background: var(--if-surface, #fff);
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s ease, transform 0.15s ease;
}
.related-card:hover {
  border-color: var(--plan-accent, var(--if-primary, #ff6c2c));
  transform: translateY(-1px);
}
.related-name {
  font-size: 0.88rem;
  font-weight: 700;
}
.related-price {
  font-size: 0.78rem;
  color: var(--if-muted, #64748b);
}
.related-more {
  margin-top: 0.15rem;
  font-size: 0.72rem;
  font-weight: 650;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
}

.state {
  margin: 0;
  padding: 1.5rem 0;
  text-align: center;
  color: var(--if-muted, #64748b);
  font-size: 0.9rem;
}
.state.inline {
  padding: 0.75rem 0 0;
  text-align: left;
}
.state.err {
  color: #b42318;
}
.state a {
  display: block;
  margin-top: 0.5rem;
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
  font-weight: 650;
  text-decoration: none;
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
  color: var(--plan-accent, var(--if-primary, #ff6c2c));
}
</style>
