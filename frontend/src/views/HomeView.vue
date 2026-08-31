<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { catalogApi, customersApi } from '@/api'
import SiteHeader from '@/components/site/SiteHeader.vue'
import { useSiteTheme } from '@/composables/useSiteTheme'

const router = useRouter()
const { theme, tone, loaded: themeReady, load: loadTheme } = useSiteTheme()

const domainLocal = ref('')
const domainExt = ref('.online')
const domainBusy = ref(false)
const domainMsg = ref('')
const domainAvailable = ref<boolean | null>(null)
const checkedDomain = ref('')
const checkedPrice = ref<number | null>(null)
const statusHint = ref('')
const checkSeq = ref(0)
let statusTimer: ReturnType<typeof setInterval> | null = null

const tlds = ref<Array<{ extension: string; price_yearly: number }>>([
  { extension: '.online', price_yearly: 65 },
  { extension: '.com', price_yearly: 225 },
  { extension: '.org', price_yearly: 240 },
  { extension: '.net', price_yearly: 260 },
  { extension: '.xyz', price_yearly: 70 },
  { extension: '.store', price_yearly: 95 },
  { extension: '.tech', price_yearly: 120 },
  { extension: '.site', price_yearly: 65 },
])

const listedTlds = computed(() => {
  const order = ['.online', '.com', '.org']
  return order.map((ext) => {
    const hit = tlds.value.find((t) => t.extension.toLowerCase() === ext)
    if (hit) return hit
    const fallback = { '.online': 65, '.com': 225, '.org': 240 }[ext] ?? 0
    return { extension: ext, price_yearly: fallback }
  })
})

const cleanName = computed(() => domainLocal.value.replace(/\s+/g, '').toLowerCase())
const fullDomain = computed(() => (cleanName.value ? `${cleanName.value}${domainExt.value}` : ''))
const selectedTldPrice = computed(() => {
  const hit = tlds.value.find((t) => t.extension === domainExt.value)
  return hit?.price_yearly ?? null
})

const previewHost = computed(() => (cleanName.value ? fullDomain.value : 'yourbrand.online'))

watch([domainLocal, domainExt], () => {
  if (!domainBusy.value) {
    domainAvailable.value = null
    domainMsg.value = ''
    checkedDomain.value = ''
    checkedPrice.value = null
    statusHint.value = ''
  }
})

function stopStatusHints() {
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
}

function startStatusHints(domain: string) {
  stopStatusHints()
  const steps = [`Looking up ${domain}…`, 'Checking availability…', 'Almost there…']
  let i = 0
  statusHint.value = steps[0]
  statusTimer = setInterval(() => {
    i = Math.min(i + 1, steps.length - 1)
    statusHint.value = steps[i]
  }, 700)
}

onMounted(async () => {
  document.documentElement.classList.add('home-lock')
  document.body.classList.add('home-lock')
  await loadTheme()
  try {
    const { data } = await catalogApi.meta()
    if (data.domain_prices?.length) tlds.value = data.domain_prices
  } catch {
    /* defaults */
  }
})

onUnmounted(() => {
  stopStatusHints()
  document.documentElement.classList.remove('home-lock')
  document.body.classList.remove('home-lock')
})

function isValidSld(name: string): boolean {
  return /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/.test(name) && name.length >= 2
}

async function checkDomain() {
  const name = cleanName.value
  if (!name) {
    domainAvailable.value = null
    domainMsg.value = 'Type a name first — like mystudio or mybrand.'
    checkedDomain.value = ''
    return
  }
  if (!isValidSld(name)) {
    domainAvailable.value = false
    domainMsg.value = 'Use letters, numbers, or hyphens — no spaces or symbols.'
    checkedDomain.value = fullDomain.value
    checkedPrice.value = null
    return
  }

  const seq = ++checkSeq.value
  const domain = fullDomain.value
  domainBusy.value = true
  domainAvailable.value = null
  domainMsg.value = ''
  checkedDomain.value = domain
  checkedPrice.value = selectedTldPrice.value
  startStatusHints(domain)

  try {
    const { data } = await customersApi.checkDomain(name, domainExt.value)
    if (seq !== checkSeq.value) return
    domainAvailable.value = data.available
    checkedDomain.value = data.domain
    checkedPrice.value = Number(data.price_yearly)
    domainMsg.value =
      data.message ||
      (data.available ? `${data.domain} is available.` : `${data.domain} is already taken.`)
  } catch {
    if (seq !== checkSeq.value) return
    domainAvailable.value = null
    domainMsg.value = 'Could not check that domain. Try again.'
  } finally {
    if (seq === checkSeq.value) {
      stopStatusHints()
      statusHint.value = ''
      domainBusy.value = false
    }
  }
}

function buyDomainOnly() {
  if (domainAvailable.value && cleanName.value) {
    localStorage.setItem('ifnotus_selected_domain', fullDomain.value)
    localStorage.setItem('ifnotus_domain_only', '1')
  }
  router.push({
    name: 'portal-signup',
    query: { domain: fullDomain.value, domain_only: '1' },
  })
}

function startWithDomain() {
  if (domainAvailable.value && cleanName.value) {
    localStorage.setItem('ifnotus_selected_domain', fullDomain.value)
    localStorage.removeItem('ifnotus_domain_only')
  }
  router.push({
    name: 'portal-signup',
    query: domainAvailable.value ? { domain: fullDomain.value } : {},
  })
}

function clearAndRetry() {
  domainLocal.value = ''
  domainAvailable.value = null
  domainMsg.value = ''
  checkedDomain.value = ''
  checkedPrice.value = null
}
</script>

<template>
  <div class="home" :class="[theme, { ready: themeReady }]">
    <SiteHeader active="home" :tone="tone" surface="solid" />

    <main class="stage">
      <div class="atmosphere" aria-hidden="true">
        <div class="mesh" />
        <div class="wash" />
      </div>

      <div class="stage-inset">
        <section class="copy">
          <p class="brand">IFNOTUS</p>
          <h1>Hosting that starts with your name.</h1>
          <p class="lede">
            Check a domain, pick a plan, and go live with SSL, mail, and backups — provisioned in minutes.
          </p>

          <form class="finder" @submit.prevent="checkDomain">
            <label class="sr-only" for="domain-name">Domain name</label>
            <div class="finder-row">
              <input
                id="domain-name"
                v-model="domainLocal"
                type="text"
                autocomplete="off"
                spellcheck="false"
                placeholder="yourbrand"
                maxlength="63"
                :disabled="domainBusy"
              />
              <select v-model="domainExt" aria-label="Domain extension" :disabled="domainBusy">
                <option v-for="t in tlds" :key="t.extension" :value="t.extension">
                  {{ t.extension }}
                </option>
              </select>
              <button type="submit" class="go" :disabled="domainBusy">
                <i
                  class="fa-solid"
                  :class="domainBusy ? 'fa-spinner fa-spin' : 'fa-magnifying-glass'"
                  aria-hidden="true"
                />
                <span>{{ domainBusy ? 'Checking' : 'Check' }}</span>
              </button>
            </div>
          </form>

          <p class="prices" aria-label="Domain prices">
            <template v-for="(t, i) in listedTlds" :key="t.extension">
              <span v-if="i">·</span>
              <span>{{ t.extension }} ₵{{ t.price_yearly }}/yr</span>
            </template>
          </p>

          <div
            v-if="domainBusy || domainMsg"
            class="result"
            :class="{
              loading: domainBusy,
              ok: !domainBusy && domainAvailable === true,
              bad: !domainBusy && domainAvailable === false,
            }"
            role="status"
            aria-live="polite"
          >
            <p class="result-line">
              <template v-if="domainBusy">{{ statusHint }}</template>
              <template v-else-if="domainAvailable === true">
                {{ checkedDomain || fullDomain }} is available
                <span v-if="checkedPrice != null"> — ₵{{ checkedPrice }}/yr</span>
              </template>
              <template v-else-if="domainAvailable === false">
                {{ checkedDomain || fullDomain }} is taken
              </template>
              <template v-else>{{ domainMsg }}</template>
            </p>
            <div v-if="!domainBusy" class="result-actions">
              <button v-if="domainAvailable" type="button" class="go" @click="buyDomainOnly">
                <i class="fa-solid fa-globe" aria-hidden="true" />
                Buy domain only (₵{{ checkedPrice || selectedTldPrice || 65 }}/yr)
              </button>
              <button v-if="domainAvailable" type="button" class="again" @click="startWithDomain">
                Get with hosting pack
                <i class="fa-solid fa-arrow-right" aria-hidden="true" />
              </button>
              <button
                v-else-if="domainAvailable === false"
                type="button"
                class="again"
                @click="clearAndRetry"
              >
                Try another name
              </button>
              <router-link v-if="domainAvailable" class="plans" :to="{ name: 'plans' }">
                Or browse plans
              </router-link>
            </div>
          </div>

          <p v-else class="cta-alt">
            Already know your plan?
            <router-link :to="{ name: 'plans' }">Browse hosting packages</router-link>
          </p>
        </section>

        <aside class="visual" aria-hidden="true">
          <div class="panel">
            <div class="panel-top">
              <span class="dot" />
              <span class="dot" />
              <span class="dot" />
              <span class="url">{{ previewHost }}</span>
            </div>
            <div class="panel-body">
              <div class="panel-side">
                <span /><span /><span /><span />
              </div>
              <div class="panel-main">
                <div class="bar wide" />
                <div class="bar mid" />
                <div class="tiles">
                  <span /><span /><span />
                </div>
                <div class="bar mid soft" />
                <div class="bar short soft" />
              </div>
            </div>
            <p class="panel-caption">Your site · live on IFNOTUS</p>
          </div>
        </aside>
      </div>

      <footer class="foot">
        <router-link :to="{ name: 'contact' }">Contact</router-link>
        <span aria-hidden="true">·</span>
        <router-link :to="{ name: 'plans' }">Plans</router-link>
        <span aria-hidden="true">·</span>
        <span>© IFNOTUS</span>
      </footer>
    </main>
  </div>
</template>

<style>
html.home-lock,
body.home-lock {
  overflow: hidden;
  overscroll-behavior: none;
  height: 100%;
}
</style>

<style scoped>
.home {
  height: 100vh;
  height: 100dvh;
  max-height: 100dvh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  font-family: 'Figtree', 'Segoe UI', sans-serif;
  color: #f4f1ec;
  background: #12161a;
  opacity: 0;
  transition: opacity 0.25s ease;
}
.home.ready {
  opacity: 1;
}

.stage {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.atmosphere {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}
.mesh {
  position: absolute;
  inset: -10%;
  background:
    radial-gradient(ellipse 55% 45% at 18% 35%, rgba(255, 108, 44, 0.28), transparent 60%),
    radial-gradient(ellipse 50% 40% at 88% 70%, rgba(255, 108, 44, 0.12), transparent 55%),
    linear-gradient(160deg, #0e1216 0%, #1a2229 48%, #12161a 100%);
  animation: mesh-drift 18s ease-in-out infinite alternate;
}
.wash {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(244, 241, 236, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(244, 241, 236, 0.035) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(ellipse 70% 60% at 50% 40%, #000 20%, transparent 75%);
  opacity: 0.7;
}

.stage-inset {
  position: relative;
  z-index: 1;
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  max-width: 76rem;
  margin: 0 auto;
  padding: clamp(1rem, 3vh, 2rem) clamp(1.15rem, 3vw, 2rem);
  box-sizing: border-box;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 1.25rem;
  align-items: center;
}
@media (min-width: 960px) {
  .stage-inset {
    grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
    gap: clamp(1.5rem, 4vw, 3rem);
  }
}

.copy {
  min-width: 0;
  animation: rise 0.7s cubic-bezier(0.22, 1, 0.36, 1) both;
}
.brand {
  margin: 0;
  font-family: 'Sora', sans-serif;
  font-size: clamp(2.4rem, 7vw, 4.25rem);
  font-weight: 800;
  letter-spacing: -0.06em;
  line-height: 0.92;
  color: #fff;
}
.copy h1 {
  margin: 0.85rem 0 0;
  max-width: 18ch;
  font-family: 'Sora', sans-serif;
  font-size: clamp(1.35rem, 3.2vw, 2rem);
  font-weight: 650;
  letter-spacing: -0.035em;
  line-height: 1.15;
  color: #f4f1ec;
}
.lede {
  margin: 0.7rem 0 0;
  max-width: 34rem;
  font-size: clamp(0.92rem, 1.7vw, 1.05rem);
  line-height: 1.55;
  color: rgba(244, 241, 236, 0.68);
}

.finder {
  margin-top: 1.35rem;
  max-width: 34rem;
  animation: rise 0.75s cubic-bezier(0.22, 1, 0.36, 1) 0.08s both;
}
.finder-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 0.4rem;
  padding: 0.35rem;
  border-radius: 0.75rem;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(244, 241, 236, 0.14);
  backdrop-filter: blur(10px);
}
.finder-row input,
.finder-row select {
  border: none;
  border-radius: 0.5rem;
  padding: 0.8rem 0.85rem;
  font: inherit;
  font-size: 0.95rem;
  background: transparent;
  color: #fff;
}
.finder-row input::placeholder {
  color: rgba(244, 241, 236, 0.4);
}
.finder-row select {
  color: rgba(244, 241, 236, 0.9);
  background: rgba(0, 0, 0, 0.2);
  cursor: pointer;
}
.finder-row select option {
  color: #161a1d;
  background: #fff;
}
.finder-row input:focus,
.finder-row select:focus {
  outline: none;
  background: rgba(255, 255, 255, 0.06);
}
@media (max-width: 560px) {
  .finder-row {
    grid-template-columns: 1fr 1fr;
  }
  .finder-row input {
    grid-column: 1 / -1;
  }
  .finder-row .go {
    grid-column: 1 / -1;
  }
}

.go {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  border: none;
  border-radius: 0.5rem;
  padding: 0.75rem 1.05rem;
  font: inherit;
  font-size: 0.88rem;
  font-weight: 700;
  cursor: pointer;
  background: var(--if-primary, #ff6c2c);
  color: #fff;
  transition: filter 0.15s ease, transform 0.15s ease;
}
.go:hover:not(:disabled) {
  filter: brightness(1.06);
}
.go:disabled {
  opacity: 0.7;
  cursor: wait;
}

.prices {
  margin: 0.7rem 0 0;
  font-size: 0.75rem;
  letter-spacing: 0.01em;
  color: rgba(244, 241, 236, 0.48);
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.55rem;
}

.cta-alt {
  margin: 1rem 0 0;
  font-size: 0.82rem;
  color: rgba(244, 241, 236, 0.55);
}
.cta-alt a,
.plans {
  color: #ff9a66;
  font-weight: 650;
  text-decoration: none;
}
.cta-alt a:hover,
.plans:hover {
  text-decoration: underline;
}

.result {
  margin-top: 0.9rem;
  max-width: 34rem;
  padding: 0.85rem 0 0;
  border-top: 1px solid rgba(244, 241, 236, 0.12);
  animation: rise 0.35s ease both;
}
.result-line {
  margin: 0;
  font-size: 0.92rem;
  font-weight: 650;
  color: #f4f1ec;
}
.result.ok .result-line {
  color: #6ee7b7;
}
.result.bad .result-line {
  color: #fca5a5;
}
.result.loading .result-line {
  color: rgba(244, 241, 236, 0.75);
}
.result-actions {
  margin-top: 0.7rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem 1rem;
}
.again {
  border: none;
  background: none;
  padding: 0;
  font: inherit;
  font-size: 0.85rem;
  font-weight: 650;
  color: rgba(244, 241, 236, 0.7);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 0.15em;
}
.again:hover {
  color: #fff;
}

.visual {
  display: none;
  justify-content: center;
  align-items: center;
  min-height: 0;
  animation: rise 0.85s cubic-bezier(0.22, 1, 0.36, 1) 0.12s both;
}
@media (min-width: 960px) {
  .visual {
    display: flex;
  }
}

.panel {
  width: min(100%, 26rem);
  transform: perspective(1200px) rotateY(-8deg) rotateX(4deg);
  transform-origin: center;
  transition: transform 0.5s ease;
}
.panel:hover {
  transform: perspective(1200px) rotateY(-4deg) rotateX(2deg);
}
.panel-top {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.65rem 0.85rem;
  border-radius: 0.85rem 0.85rem 0 0;
  background: rgba(20, 24, 28, 0.92);
  border: 1px solid rgba(244, 241, 236, 0.14);
  border-bottom: none;
}
.dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 50%;
  background: rgba(244, 241, 236, 0.28);
}
.dot:first-child {
  background: #ff6c2c;
}
.url {
  margin-left: 0.55rem;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 0.68rem;
  color: rgba(244, 241, 236, 0.55);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.panel-body {
  display: grid;
  grid-template-columns: 3.25rem 1fr;
  min-height: 16rem;
  border-radius: 0 0 0.85rem 0.85rem;
  background: linear-gradient(165deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.04));
  border: 1px solid rgba(244, 241, 236, 0.14);
  overflow: hidden;
}
.panel-side {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 0.9rem 0.65rem;
  background: rgba(0, 0, 0, 0.28);
  border-right: 1px solid rgba(244, 241, 236, 0.08);
}
.panel-side span {
  height: 0.35rem;
  border-radius: 0.2rem;
  background: rgba(244, 241, 236, 0.22);
}
.panel-side span:nth-child(1) {
  width: 70%;
  background: #ff6c2c;
}
.panel-side span:nth-child(2) {
  width: 90%;
}
.panel-side span:nth-child(3) {
  width: 55%;
}
.panel-side span:nth-child(4) {
  width: 75%;
}
.panel-main {
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}
.bar {
  height: 0.55rem;
  border-radius: 0.25rem;
  background: rgba(244, 241, 236, 0.28);
}
.bar.wide {
  width: 55%;
  height: 0.75rem;
  background: rgba(255, 108, 44, 0.85);
}
.bar.mid {
  width: 78%;
}
.bar.short {
  width: 42%;
}
.bar.soft {
  background: rgba(244, 241, 236, 0.14);
}
.tiles {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.45rem;
  margin: 0.25rem 0;
}
.tiles span {
  aspect-ratio: 1.35;
  border-radius: 0.4rem;
  background: rgba(244, 241, 236, 0.1);
  border: 1px solid rgba(244, 241, 236, 0.08);
}
.tiles span:first-child {
  background: color-mix(in srgb, #ff6c2c 28%, transparent);
  border-color: color-mix(in srgb, #ff6c2c 35%, transparent);
}
.panel-caption {
  margin: 0.85rem 0 0;
  text-align: center;
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(244, 241, 236, 0.42);
}

.foot {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.5rem 0.65rem;
  padding: 0.55rem clamp(1.15rem, 3vw, 2rem) 0.9rem;
  font-size: 0.72rem;
  color: rgba(244, 241, 236, 0.42);
  border-top: 1px solid rgba(244, 241, 236, 0.08);
}
.foot a {
  color: inherit;
  text-decoration: none;
  font-weight: 600;
}
.foot a:hover {
  color: #ff9a66;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@keyframes mesh-drift {
  from {
    transform: scale(1) translate(0, 0);
  }
  to {
    transform: scale(1.05) translate(-1.5%, 1%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .mesh,
  .copy,
  .finder,
  .visual,
  .result {
    animation: none;
  }
  .panel,
  .panel:hover {
    transform: none;
  }
}
</style>
