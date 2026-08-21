<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { isPureCustomer, isStaffUser } from '@/lib/roles'
import { useAuthStore } from '@/stores/auth'

defineProps<{
  active?: 'home' | 'plans'
  tone?: 'light' | 'dark'
}>()

const auth = useAuthStore()
const open = ref(false)

const panelLink = computed(() => {
  if (!auth.user) return null
  if (isPureCustomer(auth.user)) return { name: 'portal-dashboard' as const, label: 'My panel' }
  if (isStaffUser(auth.user)) return { name: 'dashboard' as const, label: 'Staff panel' }
  return { name: 'portal-dashboard' as const, label: 'My panel' }
})

function closeMenu() {
  open.value = false
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') closeMenu()
}

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  if (auth.isAuthenticated && !auth.user) {
    try {
      await auth.fetchUser()
    } catch {
      /* public */
    }
  }
})

onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <header class="shell" :class="{ dark: tone === 'dark', open }">
    <div class="bar">
      <router-link :to="{ name: 'home' }" class="brand" aria-label="IFNOTUS home" @click="closeMenu">
        <span class="mark" aria-hidden="true">IF</span>
        <span class="word">IFNOTUS</span>
      </router-link>

      <nav class="desk" aria-label="Primary">
        <router-link class="link" :to="{ name: 'home' }" :class="{ on: active === 'home' }">
          Home
        </router-link>
        <router-link class="link" :to="{ name: 'plans' }" :class="{ on: active === 'plans' }">
          Plans
        </router-link>
        <router-link class="link" :to="{ name: 'contact' }">Contact</router-link>
        <router-link class="link" :to="{ name: 'portal-signup' }">Sign up</router-link>
        <span class="rail" aria-hidden="true" />
        <router-link v-if="panelLink" class="link soft" :to="{ name: panelLink.name }">
          {{ panelLink.label }}
        </router-link>
        <router-link v-else class="link soft" :to="{ name: 'login' }">Log in</router-link>
        <router-link class="cta" :to="{ name: 'plans' }">View plans</router-link>
      </nav>

      <button
        type="button"
        class="burger"
        :aria-expanded="open"
        aria-controls="site-nav-mobile"
        aria-label="Menu"
        @click="open = !open"
      >
        <span />
        <span />
      </button>
    </div>

    <div id="site-nav-mobile" class="mobile" :hidden="!open">
      <nav aria-label="Mobile">
        <router-link :to="{ name: 'home' }" :class="{ on: active === 'home' }" @click="closeMenu">
          Home
        </router-link>
        <router-link :to="{ name: 'plans' }" :class="{ on: active === 'plans' }" @click="closeMenu">
          Plans
        </router-link>
        <router-link :to="{ name: 'contact' }" @click="closeMenu">Contact</router-link>
        <router-link :to="{ name: 'portal-signup' }" @click="closeMenu">Sign up</router-link>
        <router-link v-if="panelLink" :to="{ name: panelLink.name }" @click="closeMenu">
          {{ panelLink.label }}
        </router-link>
        <router-link v-else :to="{ name: 'login' }" @click="closeMenu">Log in</router-link>
        <router-link class="cta" :to="{ name: 'plans' }" @click="closeMenu">View plans</router-link>
      </nav>
    </div>
  </header>
</template>

<style scoped>
.shell {
  position: sticky;
  top: 0;
  z-index: 40;
  isolation: isolate;
}
.shell::before {
  content: '';
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(18px) saturate(1.2);
  border-bottom: 1px solid rgba(18, 23, 28, 0.06);
  z-index: -1;
}
.shell.dark::before {
  background: rgba(8, 10, 14, 0.55);
  border-bottom-color: rgba(255, 255, 255, 0.08);
}
.bar {
  max-width: 72rem;
  margin: 0 auto;
  padding: 0.75rem clamp(1.25rem, 4.5vw, 2.5rem);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  box-sizing: border-box;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 0.65rem;
  text-decoration: none;
  color: inherit;
  flex-shrink: 0;
}
.mark {
  width: 2rem;
  height: 2rem;
  border-radius: 0.55rem;
  background: var(--if-primary, #ff6c2c);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: 'Sora', sans-serif;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.word {
  font-family: 'Sora', sans-serif;
  font-weight: 700;
  letter-spacing: -0.05em;
  font-size: 1.05rem;
  color: #12171c;
}
.shell.dark .word {
  color: #fff;
}
.desk {
  display: none;
  align-items: center;
  gap: 0.15rem;
}
.link {
  text-decoration: none;
  font-size: 0.875rem;
  font-weight: 500;
  letter-spacing: -0.01em;
  color: #5a6570;
  padding: 0.5rem 0.85rem;
  border-radius: 999px;
  transition: color 0.15s ease, background 0.15s ease;
}
.shell.dark .link {
  color: rgba(245, 247, 250, 0.72);
}
.link:hover,
.link.on {
  color: #12171c;
  background: rgba(18, 23, 28, 0.05);
}
.shell.dark .link:hover,
.shell.dark .link.on {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
}
.link.soft {
  color: #7a8490;
}
.rail {
  width: 1px;
  height: 1rem;
  margin: 0 0.45rem;
  background: rgba(18, 23, 28, 0.12);
}
.shell.dark .rail {
  background: rgba(255, 255, 255, 0.16);
}
.cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: 0.35rem;
  text-decoration: none;
  border-radius: 999px;
  padding: 0.55rem 1.1rem;
  font-size: 0.85rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  background: #12171c;
  color: #fff !important;
  transition: transform 0.15s ease, background 0.15s ease;
}
.shell.dark .cta {
  background: var(--if-primary, #ff6c2c);
}
.cta:hover {
  transform: translateY(-1px);
  background: var(--if-primary, #ff6c2c);
}
.burger {
  width: 2.5rem;
  height: 2.5rem;
  border: none;
  border-radius: 0.65rem;
  background: rgba(18, 23, 28, 0.04);
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  cursor: pointer;
}
.shell.dark .burger {
  background: rgba(255, 255, 255, 0.08);
}
.burger span {
  display: block;
  width: 1.05rem;
  height: 1.5px;
  border-radius: 2px;
  background: #12171c;
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.shell.dark .burger span {
  background: #fff;
}
.shell.open .burger span:first-child {
  transform: translateY(3.5px) rotate(45deg);
}
.shell.open .burger span:last-child {
  transform: translateY(-3.5px) rotate(-45deg);
}
.mobile {
  border-top: 1px solid rgba(18, 23, 28, 0.06);
  padding: 0.75rem clamp(1.25rem, 4.5vw, 2.5rem) 1.15rem;
}
.shell.dark .mobile {
  border-top-color: rgba(255, 255, 255, 0.08);
}
.mobile nav {
  display: grid;
  gap: 0.25rem;
}
.mobile a {
  text-decoration: none;
  color: #3a4450;
  font-weight: 500;
  font-size: 0.95rem;
  padding: 0.75rem 0.85rem;
  border-radius: 0.65rem;
}
.shell.dark .mobile a {
  color: rgba(245, 247, 250, 0.85);
}
.mobile a.on,
.mobile a:hover {
  background: rgba(18, 23, 28, 0.04);
  color: #12171c;
}
.shell.dark .mobile a.on,
.shell.dark .mobile a:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}
.mobile .cta {
  margin: 0.5rem 0 0;
  text-align: center;
}
@media (min-width: 860px) {
  .desk {
    display: flex;
  }
  .burger,
  .mobile {
    display: none;
  }
}
</style>
