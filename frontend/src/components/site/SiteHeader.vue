<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import UiBrandMark from '@/components/ui/UiBrandMark.vue'
import { isPureCustomer, isStaffUser } from '@/lib/roles'
import { useAuthStore } from '@/stores/auth'

defineProps<{
  active?: 'home' | 'plans'
  tone?: 'light' | 'dark'
  surface?: 'glass' | 'solid'
}>()

const route = useRoute()
const auth = useAuthStore()
const open = ref(false)

const navItems = [
  { id: 'home', label: 'Home', to: { name: 'home' } },
  { id: 'plans', label: 'Plans', to: { name: 'plans' } },
  { id: 'contact', label: 'Contact', to: { name: 'contact' } },
] as const

const panelLink = computed(() => {
  if (!auth.user) return null
  if (isPureCustomer(auth.user)) return { name: 'portal-dashboard' as const, label: 'My panel', href: '' }
  if (isStaffUser(auth.user)) {
    return { name: 'dashboard' as const, label: 'Staff panel', href: 'https://cpanel.ifnotus.space/' }
  }
  return { name: 'portal-dashboard' as const, label: 'My panel', href: '' }
})

function isActive(id: string) {
  if (id === 'home') return route.name === 'home'
  if (id === 'plans') return route.name === 'plans'
  if (id === 'contact') return route.name === 'contact'
  return false
}

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
  <header class="nav" :class="{ open }">
    <div class="nav-inset">
      <UiBrandMark inverted :to="{ name: 'home' }" @click="closeMenu" />

      <nav class="nav-links" aria-label="Primary">
        <router-link
          v-for="item in navItems"
          :key="item.id"
          :to="item.to"
          class="nav-link"
          :class="{ on: isActive(item.id) || active === item.id }"
        >
          {{ item.label }}
        </router-link>
      </nav>

      <div class="nav-actions">
        <template v-if="panelLink">
          <a v-if="panelLink.href" class="btn btn-solid" :href="panelLink.href">
            {{ panelLink.label }}
          </a>
          <router-link v-else class="btn btn-solid" :to="{ name: panelLink.name }">
            {{ panelLink.label }}
          </router-link>
        </template>
        <template v-else>
          <router-link class="btn btn-ghost" :to="{ name: 'login' }">Log in</router-link>
          <router-link class="btn btn-solid" :to="{ name: 'portal-signup' }">Get started</router-link>
        </template>

        <button
          type="button"
          class="nav-toggle"
          :aria-expanded="open"
          aria-controls="site-nav-drawer"
          aria-label="Menu"
          @click="open = !open"
        >
          <i class="fa-solid" :class="open ? 'fa-xmark' : 'fa-bars'" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div
      id="site-nav-drawer"
      class="nav-drawer"
      :class="{ open }"
      :hidden="!open"
      @click.self="closeMenu"
    >
      <nav class="drawer-nav" aria-label="Mobile">
        <router-link
          v-for="item in navItems"
          :key="`m-${item.id}`"
          :to="item.to"
          class="drawer-link"
          :class="{ on: isActive(item.id) || active === item.id }"
          @click="closeMenu"
        >
          {{ item.label }}
        </router-link>

        <div class="drawer-divider" aria-hidden="true" />

        <template v-if="panelLink">
          <a v-if="panelLink.href" class="drawer-cta" :href="panelLink.href" @click="closeMenu">
            {{ panelLink.label }}
          </a>
          <router-link v-else class="drawer-cta" :to="{ name: panelLink.name }" @click="closeMenu">
            {{ panelLink.label }}
          </router-link>
        </template>
        <template v-else>
          <router-link class="drawer-link" :to="{ name: 'login' }" @click="closeMenu">
            <i class="fa-solid fa-right-to-bracket" aria-hidden="true" /> Log in
          </router-link>
          <router-link class="drawer-cta" :to="{ name: 'portal-signup' }" @click="closeMenu">
            Get started
          </router-link>
        </template>
      </nav>
    </div>
  </header>
</template>

<style scoped>
.nav {
  position: relative;
  z-index: 50;
  flex-shrink: 0;
  background: var(--if-ink, #161a1d);
  border-bottom: 1px solid color-mix(in srgb, #fff 8%, transparent);
  box-shadow: 0 4px 24px rgb(0 0 0 / 0.12);
}

.nav-inset {
  max-width: 76rem;
  margin: 0 auto;
  padding: 0.65rem clamp(1rem, 3vw, 2rem);
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 1rem;
  box-sizing: border-box;
}

.nav-links {
  display: none;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
}

.nav-link {
  position: relative;
  text-decoration: none;
  font-size: 0.84rem;
  font-weight: 550;
  letter-spacing: 0.01em;
  color: rgb(255 255 255 / 0.62);
  padding: 0.45rem 0.85rem;
  border-radius: 0.45rem;
  transition: color 0.15s ease, background 0.15s ease;
}
.nav-link:hover {
  color: #fff;
  background: rgb(255 255 255 / 0.06);
}
.nav-link.on {
  color: #fff;
  font-weight: 650;
}
.nav-link.on::after {
  content: '';
  position: absolute;
  left: 0.85rem;
  right: 0.85rem;
  bottom: 0.2rem;
  height: 2px;
  border-radius: 2px;
  background: var(--if-primary, #ff6c2c);
}

.nav-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.45rem;
}

.btn {
  display: none;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  border-radius: 0.5rem;
  padding: 0.48rem 0.9rem;
  font-size: 0.82rem;
  font-weight: 650;
  white-space: nowrap;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.btn-ghost {
  color: rgb(255 255 255 / 0.82);
  border: 1px solid rgb(255 255 255 / 0.18);
  background: transparent;
}
.btn-ghost:hover {
  color: #fff;
  border-color: rgb(255 255 255 / 0.35);
  background: rgb(255 255 255 / 0.06);
}
.btn-solid {
  color: #fff;
  border: 1px solid transparent;
  background: var(--if-primary, #ff6c2c);
}
.btn-solid:hover {
  background: var(--if-primary-hover, #e85a1c);
}

.nav-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.4rem;
  height: 2.4rem;
  border: 1px solid rgb(255 255 255 / 0.14);
  border-radius: 0.55rem;
  background: rgb(255 255 255 / 0.06);
  color: #fff;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.nav-toggle:hover {
  background: rgb(255 255 255 / 0.1);
  border-color: rgb(255 255 255 / 0.25);
}

.nav-drawer {
  position: fixed;
  inset: 0;
  top: 3.35rem;
  background: rgb(0 0 0 / 0.45);
  backdrop-filter: blur(4px);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s ease;
}
.nav-drawer.open {
  opacity: 1;
  pointer-events: auto;
}

.drawer-nav {
  margin: 0.65rem clamp(1rem, 3vw, 2rem);
  padding: 0.65rem;
  border-radius: 0.85rem;
  background: var(--if-surface, #fff);
  border: 1px solid var(--if-border, #e7e2db);
  box-shadow: 0 16px 40px rgb(0 0 0 / 0.18);
  display: grid;
  gap: 0.2rem;
}
.drawer-link {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  text-decoration: none;
  color: var(--if-ink, #161a1d);
  font-size: 0.92rem;
  font-weight: 550;
  padding: 0.75rem 0.85rem;
  border-radius: 0.55rem;
}
.drawer-link.on,
.drawer-link:hover {
  background: color-mix(in srgb, var(--if-primary, #ff6c2c) 10%, var(--if-paper, #f4f1ec));
  color: var(--if-ink, #161a1d);
}
.drawer-link.on {
  font-weight: 700;
}
.drawer-divider {
  height: 1px;
  margin: 0.25rem 0.35rem;
  background: var(--if-border, #e7e2db);
}
.drawer-cta {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 0.15rem;
  padding: 0.75rem 0.85rem;
  border-radius: 0.55rem;
  text-decoration: none;
  font-size: 0.92rem;
  font-weight: 700;
  color: #fff;
  background: var(--if-primary, #ff6c2c);
}
.drawer-cta:hover {
  background: var(--if-primary-hover, #e85a1c);
}

@media (min-width: 860px) {
  .nav-links {
    display: flex;
  }
  .btn {
    display: inline-flex;
  }
  .nav-toggle,
  .nav-drawer {
    display: none;
  }
}
</style>
