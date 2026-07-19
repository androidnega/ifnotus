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
  <div class="login-terminal relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-8">
    <div class="login-terminal__grid pointer-events-none absolute inset-0" aria-hidden="true" />
    <div class="login-terminal__scan pointer-events-none absolute inset-0" aria-hidden="true" />

    <form
      class="relative z-10 w-full max-w-sm overflow-hidden rounded-lg border border-emerald-500/25 bg-[#07110c]/92 shadow-[0_0_0_1px_rgba(16,185,129,0.08),0_24px_60px_rgba(0,0,0,0.55)] backdrop-blur-sm"
      @submit.prevent="handleLogin"
    >
      <div class="flex items-center gap-2 border-b border-emerald-500/20 bg-[#0a1810] px-3 py-2">
        <span class="h-2 w-2 rounded-full bg-red-500/80" />
        <span class="h-2 w-2 rounded-full bg-amber-400/80" />
        <span class="h-2 w-2 rounded-full bg-emerald-400/80" />
        <p class="ml-2 truncate font-mono text-[11px] tracking-wide text-emerald-300/70">
          root@ifnotus:~ — auth
        </p>
      </div>

      <div class="space-y-3 px-4 py-4 font-mono text-sm text-emerald-100/90">
        <div>
          <h1 class="text-base font-semibold tracking-tight text-emerald-50">
            IFNOTUS<span class="login-cursor ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 bg-emerald-400 align-middle" />
          </h1>
          <p class="mt-0.5 text-[11px] text-emerald-500/70">authorized operators only</p>
        </div>

        <div class="space-y-2.5">
          <label class="block">
            <span class="mb-1 block text-[10px] uppercase tracking-[0.14em] text-emerald-500/80">
              login
            </span>
            <div class="flex items-center gap-2 rounded border border-emerald-500/20 bg-black/35 px-3 py-1.5 focus-within:border-emerald-400/50">
              <span class="shrink-0 text-emerald-500">$</span>
              <input
                ref="emailInput"
                v-model="email"
                type="text"
                autocomplete="username"
                required
                placeholder="email"
                class="w-full bg-transparent text-sm text-emerald-100 placeholder:text-emerald-800 focus:outline-none"
              />
            </div>
          </label>

          <label class="block">
            <span class="mb-1 block text-[10px] uppercase tracking-[0.14em] text-emerald-500/80">
              password
            </span>
            <div class="flex items-center gap-2 rounded border border-emerald-500/20 bg-black/35 px-3 py-1.5 focus-within:border-emerald-400/50">
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

        <p v-if="auth.error" class="rounded border border-red-500/30 bg-red-950/40 px-3 py-1.5 text-[12px] text-red-300">
          error: {{ auth.error }}
        </p>

        <button
          type="submit"
          :disabled="auth.loading"
          class="group flex w-full items-center justify-between rounded border border-emerald-400/40 bg-emerald-500/15 px-3 py-2 text-left text-sm font-medium text-emerald-100 transition hover:bg-emerald-500/25 disabled:opacity-50"
        >
          <span>{{ auth.loading ? './auth --wait' : './auth --login' }}</span>
          <span class="text-emerald-400 transition group-hover:translate-x-0.5">↵</span>
        </button>
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
