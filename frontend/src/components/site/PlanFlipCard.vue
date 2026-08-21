<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { HostingPlan } from '@/types/platform'
import { packItems } from '@/lib/planPack'
import { sshHeadline } from '@/lib/planMatrix'
import { formatCpu, formatRamGb } from '@/lib/planResources'
import { planAccentFromPrice, softAccent } from '@/lib/theme'
import { useSiteTheme } from '@/composables/useSiteTheme'

const props = defineProps<{
  plan: HostingPlan
  featured?: boolean
}>()

const emit = defineEmits<{
  choose: []
}>()

const { planColors } = useSiteTheme()
const flipped = ref(false)
const flash = ref(false)
const canScroll = ref(false)
const packEl = ref<HTMLElement | null>(null)
const items = computed(() => packItems(props.plan))
const accent = computed(() =>
  planAccentFromPrice(Number(props.plan.price_monthly), planColors.value, props.plan.features),
)

const cardStyle = computed(() => ({
  '--plan-accent': accent.value,
  '--plan-accent-soft': softAccent(accent.value, 0.12),
  '--plan-accent-mid': softAccent(accent.value, 0.22),
}))

function priceLabel() {
  const n = Number(props.plan.price_monthly)
  return Number.isInteger(n) ? String(n) : String(n)
}

function measureScroll() {
  const el = packEl.value
  canScroll.value = !!el && el.scrollHeight > el.clientHeight + 12
}

function onPackScroll() {
  const el = packEl.value
  if (!el) return
  if (el.scrollTop > 8) canScroll.value = el.scrollTop + el.clientHeight < el.scrollHeight - 8
}

const flashTimer = ref<number | null>(null)

watch(flipped, async (on) => {
  flash.value = false
  canScroll.value = false
  if (flashTimer.value) window.clearTimeout(flashTimer.value)
  if (!on) return
  await nextTick()
  measureScroll()
  if (!canScroll.value) return
  flashTimer.value = window.setTimeout(() => {
    flash.value = true
    window.setTimeout(() => {
      flash.value = false
    }, 1400)
  }, 420)
})
</script>

<template>
  <article
    class="flip"
    :class="{ featured, on: flipped }"
    :style="cardStyle"
    @mouseenter="flipped = true"
    @mouseleave="flipped = false"
    @click="flipped = !flipped"
  >
    <div class="inner">
      <div class="face front">
        <div class="name-row">
          <h2>{{ plan.name }}</h2>
          <span v-if="featured" class="badge">Popular</span>
        </div>
        <p class="price">
          <span class="currency">₵</span>
          <span class="amount">{{ priceLabel() }}</span>
          <span class="unit">/ month</span>
        </p>
        <p class="ssh-flag">{{ sshHeadline(plan) }}</p>
        <ul class="front-specs">
          <li><span>CPU</span><strong>{{ formatCpu(plan.cpu_cores) }} vCPU</strong></li>
          <li><span>RAM</span><strong>{{ formatRamGb(plan.ram_gb) }}</strong></li>
          <li><span>Disk</span><strong>{{ plan.storage_gb }} GB</strong></li>
          <li><span>AI</span><strong>{{ plan.ai_credits }} credits</strong></li>
        </ul>
        <p class="hint">Hover or tap to see what’s included</p>
      </div>
      <div class="face back">
        <p class="back-kicker">What’s included</p>
        <div class="pack-wrap" :class="{ more: canScroll }">
          <span v-if="flash" class="flash" aria-hidden="true" />
          <ul ref="packEl" class="pack" @scroll="onPackScroll">
            <li v-for="item in items" :key="item.id">
              <span>{{ item.label }}</span>
              <em>{{ item.detail }}</em>
            </li>
          </ul>
          <p v-if="canScroll" class="scroll-cue">
            <span class="chev" aria-hidden="true" />
            Scroll for more
          </p>
        </div>
        <button type="button" class="pick" @click.stop="emit('choose')">Get {{ plan.name }}</button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.flip {
  --plan-accent: var(--if-primary);
  perspective: 1400px;
  height: 28rem;
  cursor: pointer;
}
.inner {
  position: relative;
  height: 100%;
  transform-style: preserve-3d;
  transition: transform 0.55s cubic-bezier(0.22, 1, 0.36, 1);
}
.flip.on .inner {
  transform: rotateY(180deg);
}
@media (hover: hover) and (pointer: fine) {
  .flip:hover .inner {
    transform: rotateY(180deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .inner { transition: none; }
  .flash, .scroll-cue .chev { animation: none; }
}
.face {
  position: absolute;
  inset: 0;
  backface-visibility: hidden;
  border-radius: 1.05rem;
  padding: 1.3rem 1.2rem 1.15rem;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.front {
  background: var(--if-surface, #fff);
  border: 1px solid var(--if-border, #e8ecf0);
  color: var(--if-ink, #0f172a);
}
.flip.featured .front {
  border-color: color-mix(in srgb, var(--plan-accent) 45%, var(--if-border, #e8ecf0));
  background: linear-gradient(180deg, var(--plan-accent-soft) 0%, var(--if-surface, #fff) 48%);
}
.back {
  transform: rotateY(180deg);
  background: #0f172a;
  color: #e2e8f0;
  border: 1px solid color-mix(in srgb, var(--plan-accent) 55%, #0f172a);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--plan-accent) 28%, transparent);
}
.name-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
}
h2 {
  margin: 0;
  font-family: Sora, sans-serif;
  font-size: 1.05rem;
  font-weight: 700;
}
.badge {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--plan-accent);
  background: var(--plan-accent-soft);
  padding: 0.25rem 0.5rem;
  border-radius: 999px;
}
.price {
  margin: 1rem 0 0;
  display: flex;
  align-items: baseline;
  gap: 0.15rem;
}
.currency { color: var(--plan-accent); font-weight: 700; }
.amount {
  font-family: Sora, sans-serif;
  font-size: 2.2rem;
  font-weight: 750;
  letter-spacing: -0.05em;
  color: var(--if-ink, #0f172a);
}
.unit { font-size: 0.8rem; color: var(--if-muted, #64748b); }
.ssh-flag {
  margin: 0.45rem 0 0;
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--plan-accent);
}
.front-specs {
  margin: 1.2rem 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.55rem;
  flex: 1;
}
.front-specs li {
  display: flex;
  justify-content: space-between;
  font-size: 0.88rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--if-border, #eef2f6);
}
.front-specs span { color: var(--if-muted, #64748b); }
.hint {
  margin: 0.6rem 0 0;
  font-size: 0.75rem;
  color: var(--if-muted, #94a3b8);
}
.back-kicker {
  margin: 0 0 0.55rem;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--plan-accent);
}
.pack-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.pack {
  margin: 0;
  padding: 0 0.15rem 1.6rem;
  list-style: none;
  overflow: auto;
  flex: 1;
  display: grid;
  gap: 0.4rem;
  scrollbar-width: thin;
  scrollbar-color: transparent transparent;
}
.pack:hover {
  scrollbar-color: rgb(148 163 184 / 0.45) transparent;
}
.pack::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.pack::-webkit-scrollbar-track {
  background: transparent;
}
.pack::-webkit-scrollbar-thumb {
  background: transparent;
  border-radius: 999px;
}
.pack:hover::-webkit-scrollbar-thumb {
  background: rgb(148 163 184 / 0.45);
}
.pack li {
  display: grid;
  gap: 0.05rem;
  font-size: 0.78rem;
}
.pack span { font-weight: 650; color: #fff; }
.pack em { font-style: normal; color: #94a3b8; font-size: 0.72rem; }
.pack-wrap.more::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 1.65rem;
  height: 2.4rem;
  pointer-events: none;
  background: linear-gradient(180deg, transparent, #0f172a 78%);
}
.flash {
  position: absolute;
  inset: 0 0 1.6rem;
  pointer-events: none;
  z-index: 2;
  background: linear-gradient(
    180deg,
    transparent 0%,
    color-mix(in srgb, var(--plan-accent) 42%, white) 42%,
    transparent 100%
  );
  mix-blend-mode: screen;
  animation: pack-flash 1.25s ease-out both;
}
.scroll-cue {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 3;
  margin: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #fff;
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.45);
}
.scroll-cue .chev {
  width: 0.45rem;
  height: 0.45rem;
  border-right: 2px solid var(--plan-accent);
  border-bottom: 2px solid var(--plan-accent);
  transform: rotate(45deg);
  animation: cue-bounce 1.1s ease-in-out infinite;
}
.pick {
  margin-top: 0.85rem;
  width: 100%;
  border: none;
  border-radius: 0.65rem;
  padding: 0.75rem;
  font-weight: 700;
  background: var(--plan-accent);
  color: #fff;
  cursor: pointer;
}
@keyframes pack-flash {
  0% { opacity: 0; transform: translateY(-55%); }
  35% { opacity: 0.85; }
  100% { opacity: 0; transform: translateY(55%); }
}
@keyframes cue-bounce {
  0%, 100% { transform: rotate(45deg) translateY(0); opacity: 0.55; }
  50% { transform: rotate(45deg) translateY(4px); opacity: 1; }
}
</style>
