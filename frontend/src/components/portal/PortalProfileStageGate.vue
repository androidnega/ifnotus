<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { customersApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { CustomerProfile } from '@/types/platform'
import {
  deferStage,
  nextProfileStage,
  profileStageProgress,
  stagePayload,
} from '@/lib/portalProfileStages'

const props = withDefaults(
  defineProps<{
    profile: CustomerProfile
    /** When true, optional stages (company / password) are also prompted. */
    includeOptional?: boolean
    /** Soft card vs full account gate. */
    mode?: 'gate' | 'card'
  }>(),
  {
    includeOptional: true,
    mode: 'gate',
  },
)

const emit = defineEmits<{
  updated: [CustomerProfile]
  complete: [CustomerProfile]
  dismiss: []
}>()

const auth = useAuthStore()
const value = ref('')
const loading = ref(false)
const error = ref('')
const celebrating = ref(false)
const tick = ref(0)

const progress = computed(() => {
  tick.value
  return profileStageProgress(props.profile)
})
const stage = computed(() => {
  tick.value
  return nextProfileStage(props.profile, { includeOptional: props.includeOptional })
})

const steps = computed(() => {
  // Dynamic trail: completed required + current remaining required/optional shown as dots
  const total = Math.max(progress.value.total, progress.value.done + (stage.value ? 1 : 0))
  return Array.from({ length: total }, (_, i) => i < progress.value.done)
})

watch(
  stage,
  (s) => {
    error.value = ''
    if (!s) {
      value.value = ''
      return
    }
    if (s.id === 'first_name') value.value = props.profile.first_name || ''
    else if (s.id === 'last_name') value.value = props.profile.last_name || ''
    else if (s.id === 'email') {
      value.value = props.profile.email?.includes('@phone.pending.ifnotus')
        ? ''
        : props.profile.email || ''
    } else if (s.id === 'phone') value.value = props.profile.phone || ''
    else if (s.id === 'company') value.value = props.profile.company || ''
    else value.value = ''
  },
  { immediate: true },
)

async function save() {
  const s = stage.value
  if (!s) return
  const trimmed = value.value.trim()
  if (s.required && !trimmed) {
    error.value = 'This field is required.'
    return
  }
  if (s.minLength && trimmed && trimmed.length < s.minLength) {
    error.value = `Please enter at least ${s.minLength} characters.`
    return
  }
  if (s.kind === 'optional' && !trimmed) {
    skip()
    return
  }
  loading.value = true
  error.value = ''
  try {
    const { data } = await customersApi.updateMe(stagePayload(s.id, trimmed))
    if (s.id === 'password') {
      deferStage('password')
    }
    if (s.id === 'email' || s.id === 'first_name' || s.id === 'last_name') {
      try {
        await auth.fetchUser()
      } catch {
        /* non-fatal */
      }
    }
    emit('updated', data)
    const next = nextProfileStage(data, { includeOptional: props.includeOptional })
    if (!next) {
      celebrating.value = true
      emit('complete', data)
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { error?: { message?: string } } } }
    error.value = err.response?.data?.error?.message ?? 'Could not save. Try again.'
  } finally {
    loading.value = false
  }
}

function skip() {
  const s = stage.value
  if (!s || s.kind !== 'optional') return
  deferStage(s.id)
  tick.value += 1
  const next = nextProfileStage(props.profile, { includeOptional: props.includeOptional })
  if (!next) {
    celebrating.value = true
    emit('complete', props.profile)
  } else {
    emit('updated', { ...props.profile })
  }
}

function onSubmit() {
  void save()
}
</script>

<template>
  <div
    v-if="stage || celebrating"
    class="stage-root"
    :class="[mode, { celebrating }]"
    role="dialog"
    aria-modal="true"
    :aria-labelledby="stage ? 'profile-stage-title' : 'profile-stage-done'"
  >
    <div class="stage-panel">
      <template v-if="celebrating || !stage">
        <p class="eyebrow">Account ready</p>
        <h2 id="profile-stage-done">You’re all set</h2>
        <p class="sub">Your account details are in place. You can update them anytime in settings.</p>
        <button type="button" class="submit" @click="emit('dismiss')">Continue to account</button>
      </template>
      <template v-else>
        <div class="progress" aria-hidden="true">
          <span
            v-for="(done, i) in steps"
            :key="i"
            class="dot"
            :class="{ on: done || i === progress.done }"
          />
        </div>
        <p class="eyebrow">
          <template v-if="stage.kind === 'required'">
            {{ progress.done + 1 }} of {{ progress.total }} · Account details
          </template>
          <template v-else>Almost done · Optional</template>
        </p>
        <h2 id="profile-stage-title">{{ stage.title }}</h2>
        <p class="sub">{{ stage.subtitle }}</p>

        <form class="fields" @submit.prevent="onSubmit">
          <input
            v-model="value"
            :type="stage.inputType"
            :placeholder="stage.placeholder"
            :autocomplete="stage.autocomplete"
            :required="stage.required"
            :minlength="stage.minLength"
            :disabled="loading"
          />
          <p v-if="error" class="err">{{ error }}</p>
          <button type="submit" class="submit" :disabled="loading">
            {{ loading ? 'Saving…' : stage.kind === 'optional' && !value.trim() ? 'Skip for now' : 'Continue' }}
          </button>
          <button
            v-if="stage.kind === 'optional' && value.trim()"
            type="button"
            class="skip"
            :disabled="loading"
            @click="skip"
          >
            Skip for now
          </button>
        </form>
      </template>
    </div>
  </div>
</template>

<style scoped>
.stage-root.gate {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 1.25rem;
  background:
    radial-gradient(ellipse 80% 50% at 50% -10%, rgba(30, 58, 95, 0.18), transparent),
    rgba(15, 23, 32, 0.45);
  backdrop-filter: blur(6px);
  animation: fade-in 0.28s ease;
}
.stage-root.card {
  position: relative;
  margin: 0 0 1.25rem;
  animation: slide-up 0.35s ease;
}
.stage-panel {
  width: min(100%, 26rem);
  background: #fff;
  border: 1px solid #e4e8ec;
  border-radius: 1.1rem;
  padding: 1.35rem 1.35rem 1.45rem;
  box-shadow: 0 18px 40px rgba(15, 23, 32, 0.12);
}
.card .stage-panel {
  width: 100%;
  box-shadow: none;
}
.progress {
  display: flex;
  gap: 0.35rem;
  margin-bottom: 0.85rem;
}
.dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 999px;
  background: #d7dde5;
  transition: background 0.2s ease, transform 0.2s ease;
}
.dot.on {
  background: #1e3a5f;
  transform: scale(1.15);
}
.eyebrow {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #7a8490;
}
h2 {
  margin: 0.35rem 0 0;
  font-family: Sora, sans-serif;
  font-size: 1.45rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: #0f1720;
}
.sub {
  margin: 0.45rem 0 0;
  color: #5c6670;
  font-size: 0.92rem;
  line-height: 1.5;
}
.fields {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  margin-top: 1.15rem;
}
.fields input {
  border: 1px solid #d7dde5;
  border-radius: 0.7rem;
  padding: 0.78rem 0.95rem;
  font-size: 0.95rem;
}
.fields input:focus {
  outline: 2px solid rgba(30, 58, 95, 0.25);
  border-color: #1e3a5f;
}
.err {
  margin: 0;
  color: #b42318;
  font-size: 0.88rem;
}
.submit {
  border: 0;
  border-radius: 999px;
  background: #0f1720;
  color: #fff;
  font-weight: 650;
  padding: 0.8rem 1rem;
  cursor: pointer;
}
.submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.skip {
  border: 0;
  background: transparent;
  color: #5c6670;
  font-size: 0.85rem;
  text-decoration: underline;
  cursor: pointer;
  padding: 0.25rem;
}
@keyframes fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
@keyframes slide-up {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
