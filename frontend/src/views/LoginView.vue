<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const emailInput = ref<HTMLInputElement | null>(null)
const bootLines = ref([
  'IFNOTUS control plane v0.1.0',
  'host: ifnotus.space',
  'session: unauthenticated',
  'awaiting credentials…',
])

onMounted(() => {
  nextTick(() => emailInput.value?.focus())
})

async function handleLogin() {
  const ok = await auth.login({ email: email.value, password: password.value })
  if (!ok) return
  const redirect = (route.query.redirect as string) || '/'
  router.push(redirect)
}
</script>

<template>
  <div class="login-terminal relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-10">
    <div class="login-terminal__grid pointer-events-none absolute inset-0" aria-hidden="true" />
    <div class="login-terminal__scan pointer-events-none absolute inset-0" aria-hidden="true" />

    <form
      class="relative z-10 w-full max-w-md overflow-hidden rounded-lg border border-emerald-500/25 bg-[#07110c]/92 shadow-[0_0_0_1px_rgba(16,185,129,0.08),0_24px_60px_rgba(0,0,0,0.55)] backdrop-blur-sm"
      @submit.prevent="handleLogin"
    >
      <div class="flex items-center gap-2 border-b border-emerald-500/20 bg-[#0a1810] px-4 py-2.5">
        <span class="h-2.5 w-2.5 rounded-full bg-red-500/80" />
        <span class="h-2.5 w-2.5 rounded-full bg-amber-400/80" />
        <span class="h-2.5 w-2.5 rounded-full bg-emerald-400/80" />
        <p class="ml-2 truncate font-mono text-[11px] tracking-wide text-emerald-300/70">
          root@ifnotus:~ — auth
        </p>
      </div>

      <div class="space-y-5 px-5 py-6 font-mono text-sm text-emerald-100/90 sm:px-6">
        <div class="space-y-1 text-[12px] leading-relaxed text-emerald-400/80">
          <p v-for="(line, i) in bootLines" :key="i" class="animate-fade-in">
            <span class="text-emerald-600">$</span> {{ line }}
          </p>
        </div>

        <div>
          <h1 class="text-lg font-semibold tracking-tight text-emerald-50">
            IFNOTUS<span class="login-cursor ml-0.5 inline-block h-4 w-2 translate-y-0.5 bg-emerald-400 align-middle" />
          </h1>
          <p class="mt-1 text-[12px] text-emerald-500/70">server access · authorized operators only</p>
        </div>

        <div class="space-y-3">
          <label class="block">
            <span class="mb-1.5 block text-[11px] uppercase tracking-[0.14em] text-emerald-500/80">
              login
            </span>
            <div class="flex items-center gap-2 rounded border border-emerald-500/20 bg-black/35 px-3 py-2 focus-within:border-emerald-400/50">
              <span class="shrink-0 text-emerald-500">$</span>
              <input
                ref="emailInput"
                v-model="email"
                type="text"
                autocomplete="username"
                required
                placeholder="admin@ifnotus.local"
                class="w-full bg-transparent text-sm text-emerald-100 placeholder:text-emerald-800 focus:outline-none"
              />
            </div>
          </label>

          <label class="block">
            <span class="mb-1.5 block text-[11px] uppercase tracking-[0.14em] text-emerald-500/80">
              password
            </span>
            <div class="flex items-center gap-2 rounded border border-emerald-500/20 bg-black/35 px-3 py-2 focus-within:border-emerald-400/50">
              <span class="shrink-0 text-emerald-500">#</span>
              <input
                v-model="password"
                type="password"
                required
                autocomplete="current-password"
                placeholder="••••••••"
                class="w-full bg-transparent text-sm tracking-widest text-emerald-100 placeholder:text-emerald-800 focus:outline-none"
              />
            </div>
          </label>
        </div>

        <p v-if="auth.error" class="rounded border border-red-500/30 bg-red-950/40 px-3 py-2 text-[12px] text-red-300">
          error: {{ auth.error }}
        </p>

        <button
          type="submit"
          :disabled="auth.loading"
          class="group flex w-full items-center justify-between rounded border border-emerald-400/40 bg-emerald-500/15 px-4 py-2.5 text-left text-sm font-medium text-emerald-100 transition hover:bg-emerald-500/25 disabled:opacity-50"
        >
          <span>{{ auth.loading ? './auth --wait' : './auth --login' }}</span>
          <span class="text-emerald-400 transition group-hover:translate-x-0.5">↵</span>
        </button>

        <p class="text-[11px] text-emerald-700">
          tip: use email <span class="text-emerald-500">admin@ifnotus.local</span>
        </p>
      </div>
    </form>
  </div>
</template>

<style scoped>
.login-terminal {
  background:
    radial-gradient(ellipse 80% 60% at 50% -10%, rgba(16, 185, 129, 0.12), transparent 55%),
    linear-gradient(180deg, #020805 0%, #05140c 45%, #020805 100%);
}

.login-terminal__grid {
  background-image:
    linear-gradient(rgba(16, 185, 129, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(16, 185, 129, 0.04) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: radial-gradient(ellipse at center, black 30%, transparent 75%);
}

.login-terminal__scan {
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0, 0, 0, 0.12) 2px,
    rgba(0, 0, 0, 0.12) 4px
  );
  opacity: 0.35;
}

.login-cursor {
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}
</style>
