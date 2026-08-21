<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { catalogApi, customersApi } from '@/api'
import SiteHeader from '@/components/site/SiteHeader.vue'
import { useSiteTheme } from '@/composables/useSiteTheme'

const router = useRouter()
const { theme, isDark, tone, load: loadTheme } = useSiteTheme()

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
  { extension: '.online', price_yearly: 50 },
  { extension: '.com', price_yearly: 250 },
  { extension: '.org', price_yearly: 180 },
])

const listedTlds = computed(() => {
  const order = ['.online', '.com', '.org']
  return order.map((ext) => {
    const hit = tlds.value.find((t) => t.extension.toLowerCase() === ext)
    if (hit) return hit
    const fallback = { '.online': 50, '.com': 250, '.org': 180 }[ext] ?? 0
    return { extension: ext, price_yearly: fallback }
  })
})

const cleanName = computed(() => domainLocal.value.replace(/\s+/g, '').toLowerCase())
const fullDomain = computed(() => (cleanName.value ? `${cleanName.value}${domainExt.value}` : ''))
const selectedTldPrice = computed(() => {
  const hit = tlds.value.find((t) => t.extension === domainExt.value)
  return hit?.price_yearly ?? null
})

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
  const steps = [
    `Looking up ${domain}…`,
    'Checking if it’s free…',
    'Almost there…',
  ]
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
    /* keep defaults */
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
      (data.available
        ? `Good news — ${data.domain} is free.`
        : `${data.domain} is already taken. Try another name.`)
  } catch {
    if (seq !== checkSeq.value) return
    domainAvailable.value = null
    domainMsg.value = 'We couldn’t check that right now. Please try again.'
  } finally {
    if (seq === checkSeq.value) {
      stopStatusHints()
      statusHint.value = ''
      domainBusy.value = false
    }
  }
}

function startWithDomain() {
  if (domainAvailable.value && cleanName.value) {
    localStorage.setItem('ifnotus_selected_domain', fullDomain.value)
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
  <div class="home" :class="theme">
    <!-- Server Dark stage -->
    <div v-if="isDark" class="stage dark-stage" aria-hidden="true">
      <img
        class="stage-img"
        src="/home-servers-hero.jpg"
        alt=""
        width="1920"
        height="1080"
        decoding="async"
        fetchpriority="high"
      />
      <div class="stage-shade" />
    </div>

    <!-- Studio Light stage -->
    <div v-else class="stage light-stage" aria-hidden="true">
      <div class="light-grid" />
    </div>

    <SiteHeader active="home" :tone="tone" />

    <main class="hero" id="top">
      <div class="hero-copy-block">
        <p class="hero-brand">IFNOTUS</p>
        <h1>Go live in minutes.</h1>
        <p class="hero-copy">
          Check a domain, choose a plan, and we set up your hosting — SSL, backups, and an AI engineer
          included.
        </p>

        <form id="domain" class="domain" @submit.prevent="checkDomain">
          <label class="sr-only" for="domain-name">Domain name</label>
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
          <button type="submit" class="cta solid" :disabled="domainBusy">
            {{ domainBusy ? 'Checking' : 'Check' }}
          </button>
        </form>

        <ul class="tld-prices" aria-label="Domain prices">
          <li v-for="t in listedTlds" :key="t.extension">
            <span>{{ t.extension }}</span>
            <strong>₵{{ t.price_yearly }}</strong>
            <em>/ year</em>
          </li>
        </ul>

        <p v-if="selectedTldPrice != null && !domainBusy && domainAvailable === null && !domainMsg" class="domain-tip">
          {{ domainExt }} is ₵{{ selectedTldPrice }}/year · hosting starts after you pick a plan
        </p>

        <div
          v-if="domainBusy || domainMsg"
          class="domain-result"
          :class="{
            loading: domainBusy,
            ok: !domainBusy && domainAvailable === true,
            bad: !domainBusy && domainAvailable === false,
            soft: !domainBusy && domainAvailable === null,
          }"
          role="status"
          aria-live="polite"
        >
          <div class="result-main">
            <span class="result-pill">
              <template v-if="domainBusy">Checking</template>
              <template v-else-if="domainAvailable === true">Available</template>
              <template v-else-if="domainAvailable === false">Taken</template>
              <template v-else>Try again</template>
            </span>
            <p class="result-domain" v-if="checkedDomain || fullDomain">
              {{ checkedDomain || fullDomain }}
            </p>
          </div>
          <p class="result-copy">{{ domainBusy ? statusHint : domainMsg }}</p>
          <p v-if="!domainBusy && domainAvailable && checkedPrice != null" class="result-price">
            Register for <strong>₵{{ checkedPrice }}</strong> / year
          </p>
          <div v-if="!domainBusy" class="result-actions">
            <button v-if="domainAvailable" type="button" class="cta solid" @click="startWithDomain">
              Continue with this domain
            </button>
            <button v-else-if="domainAvailable === false" type="button" class="cta ghost" @click="clearAndRetry">
              Try another name
            </button>
          </div>
        </div>

        <div class="hero-actions">
          <router-link class="cta ghost" :to="{ name: 'plans' }">See plans</router-link>
        </div>
        <p class="student-note">
          Students: pick Student at checkout, enter your surname, and we assign
          <strong>surname.serverlabsttu.space</strong> (or surname1, surname2 if that name is taken). No domain fee.
        </p>
      </div>

      <div v-if="!isDark" class="hero-visual" aria-hidden="true">
        <svg class="light-rack" viewBox="0 0 640 480" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="80" y="60" width="200" height="360" rx="10" stroke="#d7dde5" stroke-width="2" />
          <rect x="360" y="60" width="200" height="360" rx="10" stroke="#d7dde5" stroke-width="2" />
          <g stroke="#e4e8ec" stroke-width="2">
            <rect x="100" y="90" width="160" height="28" rx="4" />
            <rect x="100" y="140" width="160" height="28" rx="4" />
            <rect x="100" y="190" width="160" height="28" rx="4" />
            <rect x="100" y="240" width="160" height="28" rx="4" />
            <rect x="100" y="290" width="160" height="28" rx="4" />
            <rect x="100" y="340" width="160" height="28" rx="4" />
            <rect x="380" y="90" width="160" height="28" rx="4" />
            <rect x="380" y="140" width="160" height="28" rx="4" />
            <rect x="380" y="190" width="160" height="28" rx="4" />
            <rect x="380" y="240" width="160" height="28" rx="4" />
            <rect x="380" y="290" width="160" height="28" rx="4" />
            <rect x="380" y="340" width="160" height="28" rx="4" />
          </g>
          <g class="leds">
            <circle class="led led-a" cx="118" cy="104" r="3.5" />
            <circle class="led led-b" cx="132" cy="104" r="3.5" />
            <circle class="led led-c" cx="118" cy="154" r="3.5" />
            <circle class="led led-d" cx="132" cy="154" r="3.5" />
            <circle class="led led-e" cx="118" cy="204" r="3.5" />
            <circle class="led led-f" cx="118" cy="254" r="3.5" />
            <circle class="led led-g" cx="132" cy="254" r="3.5" />
            <circle class="led led-h" cx="118" cy="304" r="3.5" />
            <circle class="led led-i" cx="118" cy="354" r="3.5" />
            <circle class="led led-j" cx="398" cy="104" r="3.5" />
            <circle class="led led-k" cx="412" cy="104" r="3.5" />
            <circle class="led led-l" cx="398" cy="154" r="3.5" />
            <circle class="led led-m" cx="398" cy="204" r="3.5" />
            <circle class="led led-n" cx="412" cy="204" r="3.5" />
            <circle class="led led-o" cx="398" cy="254" r="3.5" />
            <circle class="led led-p" cx="398" cy="304" r="3.5" />
            <circle class="led led-q" cx="412" cy="304" r="3.5" />
            <circle class="led led-r" cx="398" cy="354" r="3.5" />
          </g>
        </svg>
      </div>
    </main>
  </div>
</template>

<style>
html.home-lock,
body.home-lock {
  height: 100%;
  overflow: hidden;
  overscroll-behavior: none;
}
</style>

<style scoped>
.home {
  position: relative;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  font-family: 'Figtree', 'Segoe UI', sans-serif;
  display: flex;
  flex-direction: column;
  color: var(--if-ink, #12171c);
  background: var(--if-paper, #ffffff);
}

.home.server-dark {
  color: var(--if-ink, #f5f7fa);
  background: var(--if-paper, #0b0e12);
}

.stage {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
}

.stage-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 62% center;
  transform: scale(1.01);
  animation: drift 18s ease-in-out infinite alternate;
}

.stage-shade {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, rgba(8, 10, 14, 0.88) 0%, rgba(8, 10, 14, 0.55) 48%, rgba(8, 10, 14, 0.28) 100%),
    linear-gradient(180deg, rgba(8, 10, 14, 0.55) 0%, transparent 28%, rgba(8, 10, 14, 0.72) 100%);
}

.light-stage {
  background:
    radial-gradient(900px 520px at 88% 18%, var(--if-glow, rgba(255, 108, 44, 0.08)), transparent 55%),
    linear-gradient(180deg, var(--if-surface, #ffffff) 0%, var(--if-paper, #f7f9fb) 55%, var(--if-paper, #f3f5f7) 100%);
}

.light-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(18, 23, 28, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(18, 23, 28, 0.035) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: linear-gradient(90deg, transparent 0%, #000 42%, #000 100%);
}

.led {
  fill: #c5ccd4;
}

.led-a,
.led-j,
.led-p {
  fill: #22c55e;
  animation: blink-green 1.8s ease-in-out infinite;
}
.led-b,
.led-k,
.led-n {
  fill: var(--if-primary, #ff6c2c);
  animation: blink-orange 2.4s ease-in-out infinite;
}
.led-c,
.led-l,
.led-r {
  fill: #22c55e;
  animation: blink-green 2.1s ease-in-out 0.35s infinite;
}
.led-d,
.led-m {
  fill: #22c55e;
  animation: blink-green 1.5s ease-in-out 0.7s infinite;
}
.led-e,
.led-o {
  fill: var(--if-primary, #ff6c2c);
  animation: blink-orange 1.9s ease-in-out 0.2s infinite;
}
.led-f,
.led-q {
  fill: #22c55e;
  animation: blink-green 2.6s ease-in-out 0.5s infinite;
}
.led-g {
  fill: #22c55e;
  animation: blink-green 1.4s ease-in-out 0.15s infinite;
}
.led-h {
  fill: var(--if-primary, #ff6c2c);
  animation: blink-orange 2.8s ease-in-out 0.9s infinite;
}
.led-i {
  fill: #22c55e;
  animation: blink-green 2s ease-in-out 1.1s infinite;
}

.hero {
  --home-inline: clamp(1.25rem, 4.5vw, 2.5rem);
  position: relative;
  z-index: 1;
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  gap: clamp(1rem, 3vw, 2.5rem);
  max-width: 72rem;
  width: 100%;
  margin: 0 auto;
  padding: 1.25rem var(--home-inline) 2rem;
  box-sizing: border-box;
}

.hero-copy-block {
  max-width: 36rem;
  width: 100%;
  min-width: 0;
}

.hero-visual {
  display: none;
  align-items: center;
  justify-content: center;
  min-width: 0;
  max-width: 100%;
}

.light-rack {
  display: block;
  width: 100%;
  max-width: 28rem;
  height: auto;
  max-height: min(58vh, 26rem);
  opacity: 0.95;
  animation: float 10s ease-in-out infinite alternate;
}

@media (min-width: 900px) {
  .hero {
    grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
  }

  .hero-visual {
    display: flex;
  }

  /* Dark theme uses full-bleed photo — keep copy column balanced with empty right gutter */
  .server-dark .hero {
    grid-template-columns: minmax(0, 1fr);
  }
}

.hero-brand {
  margin: 0;
  font-family: 'Sora', sans-serif;
  font-size: clamp(2.6rem, 8vw, 4.4rem);
  font-weight: 800;
  letter-spacing: -0.06em;
  line-height: 0.92;
  color: var(--if-primary, #ff6c2c);
  animation: rise 0.7s ease-out both;
}

.hero h1 {
  margin: 0.85rem 0 0;
  font-family: 'Sora', sans-serif;
  font-size: clamp(1.45rem, 3.6vw, 2.15rem);
  font-weight: 650;
  letter-spacing: -0.035em;
  line-height: 1.15;
  animation: rise 0.7s ease-out 0.08s both;
}

.server-dark .hero h1 {
  color: #fff;
}

.home:not(.server-dark) .hero h1 {
  color: #12171c;
}

.hero-copy {
  margin: 0.85rem 0 0;
  font-size: 1.02rem;
  line-height: 1.55;
  animation: rise 0.7s ease-out 0.16s both;
}

.server-dark .hero-copy {
  color: rgba(245, 247, 250, 0.78);
}

.home:not(.server-dark) .hero-copy {
  color: #5a6570;
}

.domain {
  margin-top: 1.5rem;
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 0.45rem;
  animation: rise 0.7s ease-out 0.24s both;
}

.domain input,
.domain select {
  border-radius: 0.55rem;
  padding: 0.8rem 0.9rem;
  font: inherit;
}

.server-dark .domain input,
.server-dark .domain select {
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
  backdrop-filter: blur(8px);
}

.server-dark .domain select option {
  color: #12171c;
}

.server-dark .domain input::placeholder {
  color: rgba(255, 255, 255, 0.45);
}

.home:not(.server-dark) .domain input,
.home:not(.server-dark) .domain select {
  border: 1px solid #d9dee4;
  background: #fff;
  color: #12171c;
}

.home:not(.server-dark) .domain input::placeholder {
  color: #9aa3ad;
}

.domain input:focus,
.domain select:focus {
  outline: none;
  border-color: var(--if-primary, #ff6c2c);
  box-shadow: 0 0 0 3px var(--if-primary-ring, rgba(255, 108, 44, 0.2));
}

.domain input:disabled,
.domain select:disabled {
  opacity: 0.7;
}

.tld-prices {
  margin: 0.85rem 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.45rem;
  max-width: 28rem;
}
.tld-prices li {
  display: grid;
  gap: 0.05rem;
  padding: 0.55rem 0.65rem;
  border-radius: 0.7rem;
  border: 1px solid var(--if-border, #e4e8ec);
  background: color-mix(in srgb, var(--if-surface, #fff) 88%, var(--if-primary, #ff6c2c));
}
.home.server-dark .tld-prices li {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.08);
}
.tld-prices span {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--if-primary, #ff6c2c);
}
.tld-prices strong {
  font-family: Sora, sans-serif;
  font-size: 1.05rem;
  font-weight: 750;
  letter-spacing: -0.03em;
}
.tld-prices em {
  font-style: normal;
  font-size: 0.68rem;
  color: var(--if-muted, #7a8490);
}

.domain-tip {
  margin: 0.55rem 0 0;
  font-size: 0.82rem;
  line-height: 1.4;
}

.server-dark .domain-tip {
  color: rgba(245, 247, 250, 0.55);
}

.home:not(.server-dark) .domain-tip {
  color: #7a8490;
}

.domain-result {
  margin-top: 0.85rem;
  max-width: 28rem;
  border-radius: 0.85rem;
  padding: 0.85rem 1rem;
  animation: rise 0.35s ease-out both;
}

.home:not(.server-dark) .domain-result {
  background: #fff;
  border: 1px solid #e4e8ec;
}

.server-dark .domain-result {
  background: rgba(8, 10, 14, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(10px);
}

.domain-result.ok {
  border-color: rgba(15, 122, 69, 0.35);
}

.home:not(.server-dark) .domain-result.ok {
  background: #f3fbf6;
}

.server-dark .domain-result.ok {
  background: rgba(15, 122, 69, 0.16);
}

.domain-result.bad {
  border-color: rgba(180, 35, 24, 0.28);
}

.home:not(.server-dark) .domain-result.bad {
  background: #fff6f4;
}

.server-dark .domain-result.bad {
  background: rgba(180, 35, 24, 0.16);
}

.domain-result.loading {
  border-color: var(--if-primary, #ff6c2c);
}

.result-main {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-wrap: wrap;
}

.result-pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.22rem 0.55rem;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: rgba(18, 23, 28, 0.08);
  color: #5a6570;
}

.server-dark .result-pill {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(245, 247, 250, 0.8);
}

.domain-result.ok .result-pill {
  background: rgba(15, 122, 69, 0.14);
  color: #0f7a45;
}

.server-dark .domain-result.ok .result-pill {
  background: rgba(125, 255, 168, 0.16);
  color: #7dffa8;
}

.domain-result.bad .result-pill {
  background: rgba(180, 35, 24, 0.12);
  color: #b42318;
}

.server-dark .domain-result.bad .result-pill {
  background: rgba(255, 180, 168, 0.14);
  color: #ffb4a8;
}

.domain-result.loading .result-pill {
  background: var(--if-primary-soft, rgba(255, 108, 44, 0.14));
  color: var(--if-primary, #ff6c2c);
}

.result-domain {
  margin: 0;
  font-family: 'Sora', sans-serif;
  font-size: 0.98rem;
  font-weight: 650;
  letter-spacing: -0.03em;
  word-break: break-all;
}

.result-copy {
  margin: 0.45rem 0 0;
  font-size: 0.9rem;
  line-height: 1.45;
}

.home:not(.server-dark) .result-copy {
  color: #5a6570;
}

.server-dark .result-copy {
  color: rgba(245, 247, 250, 0.78);
}

.result-price {
  margin: 0.4rem 0 0;
  font-size: 0.88rem;
}

.home:not(.server-dark) .result-price {
  color: #3a4450;
}

.server-dark .result-price {
  color: rgba(245, 247, 250, 0.88);
}

.result-actions {
  margin-top: 0.75rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.hero-actions {
  margin-top: 1.1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.7rem;
  align-items: center;
  animation: rise 0.7s ease-out 0.3s both;
}
.student-note {
  margin: 0.85rem 0 0;
  max-width: 36rem;
  font-size: 0.9rem;
  line-height: 1.45;
  color: #5c6670;
}

.cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.5rem;
  padding: 0.55rem 1rem;
  font-weight: 600;
  font-size: 0.9rem;
  text-decoration: none;
  border: none;
  cursor: pointer;
  background: var(--if-primary, #ff6c2c);
  color: #fff;
}

.cta:hover {
  filter: brightness(1.06);
}

.cta.ghost {
  background: transparent;
}

.server-dark .cta.ghost {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.22);
}

.home:not(.server-dark) .cta.ghost {
  color: #12171c;
  border: 1px solid #d9dee4;
  background: #fff;
}

.cta.solid:disabled {
  opacity: 0.65;
  cursor: not-allowed;
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
    transform: none;
  }
}

@keyframes drift {
  from {
    transform: scale(1.01) translate(0, 0);
  }
  to {
    transform: scale(1.035) translate(-0.4%, 0.4%);
  }
}

@keyframes float {
  from {
    transform: translateY(0);
  }
  to {
    transform: translateY(-0.55rem);
  }
}

@keyframes blink-green {
  0%,
  100% {
    fill: #86efac;
    opacity: 0.45;
  }
  40% {
    fill: #16a34a;
    opacity: 1;
  }
  70% {
    fill: #22c55e;
    opacity: 0.85;
  }
}

@keyframes blink-orange {
  0%,
  100% {
    fill: #fdba8c;
    opacity: 0.4;
  }
  35% {
    fill: var(--if-primary, #ff6c2c);
    opacity: 1;
  }
  65% {
    fill: #fb923c;
    opacity: 0.75;
  }
}

@media (max-width: 640px) {
  .domain {
    grid-template-columns: 1fr 1fr;
  }
  .domain input {
    grid-column: 1 / -1;
  }
  .domain .cta {
    grid-column: 1 / -1;
  }
}
</style>
