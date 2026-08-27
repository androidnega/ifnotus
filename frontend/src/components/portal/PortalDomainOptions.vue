<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { catalogApi, customersApi } from '@/api'

export type DomainKind = 'register' | 'own' | 'student'

const props = defineProps<{
  domainMode: DomainKind
  domainLocal: string
  domainExt: string
  studentSurname: string
  domainStatus?: string
}>()

const emit = defineEmits<{
  'update:domainMode': [DomainKind]
  'update:domainLocal': [string]
  'update:domainExt': [string]
  'update:studentSurname': [string]
  checkDomain: []
}>()

const domainModeModel = computed({
  get: () => props.domainMode,
  set: (v: DomainKind) => emit('update:domainMode', v),
})
const domainLocalModel = computed({
  get: () => props.domainLocal,
  set: (v: string) => emit('update:domainLocal', v),
})
const domainExtModel = computed({
  get: () => props.domainExt,
  set: (v: string) => emit('update:domainExt', v),
})
const studentSurnameModel = computed({
  get: () => props.studentSurname,
  set: (v: string) => emit('update:studentSurname', v),
})

const studentPreview = ref('')
const studentZone = ref('ifnotus.space')
const registrarEnabled = ref(true)
let previewTimer: ReturnType<typeof setTimeout> | null = null

const studentExample = computed(() => `surname.${studentZone.value}`)

const options = computed(() => {
  const list: Array<{ value: DomainKind; title: string; blurb: string }> = []
  if (registrarEnabled.value) {
    list.push({
      value: 'register',
      title: 'Register a new domain',
      blurb: 'We buy and point it after payment.',
    })
  }
  list.push(
    {
      value: 'own',
      title: 'I already have a domain',
      blurb: 'Use IFNOTUS nameservers or A records at your registrar. No domain fee.',
    },
    {
      value: 'student',
      title: 'Free IFNOTUS project address',
      blurb: `Included ${studentExample.value} hostname for student projects.`,
    },
  )
  return list
})

onMounted(async () => {
  try {
    const { data } = await catalogApi.meta()
    registrarEnabled.value = data.registrar_enabled !== false
    if (data.student_zone) {
      studentZone.value = data.student_zone
    }
    if (!registrarEnabled.value && props.domainMode === 'register') {
      emit('update:domainMode', 'student')
    }
  } catch {
    registrarEnabled.value = false
  }
})

watch(
  () => [props.domainMode, props.studentSurname] as const,
  ([mode, surname]) => {
    if (previewTimer) clearTimeout(previewTimer)
    if (mode !== 'student') {
      studentPreview.value = ''
      return
    }
    const trimmed = surname.trim()
    if (trimmed.length < 2) {
      studentPreview.value = `Enter your surname. Your site will be ${studentExample.value}.`
      return
    }
    previewTimer = setTimeout(async () => {
      try {
        const { data } = await customersApi.previewStudentHostname(trimmed)
        studentPreview.value = data.message
      } catch (e: unknown) {
        const err = e as { response?: { data?: { error?: { message?: string } } } }
        studentPreview.value = err.response?.data?.error?.message ?? 'Could not check that surname.'
      }
    }, 350)
  },
  { immediate: true },
)
</script>

<template>
  <div class="space-y-4">
    <div>
      <p class="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Domain</p>
      <div class="mt-3 grid gap-2.5 sm:grid-cols-1">
        <button
          v-for="opt in options"
          :key="opt.value"
          type="button"
          class="flex w-full items-start gap-3 rounded-2xl border px-3.5 py-3 text-left transition"
          :class="
            domainModeModel === opt.value
              ? 'border-slate-800 bg-slate-900 text-white shadow-sm'
              : 'border-slate-200 bg-white text-slate-800 hover:border-slate-300 hover:bg-slate-50'
          "
          @click="domainModeModel = opt.value"
        >
          <span
            class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold"
            :class="
              domainModeModel === opt.value
                ? 'border-white/40 bg-white text-slate-900'
                : 'border-slate-300 text-transparent'
            "
          >
            ✓
          </span>
          <span class="min-w-0">
            <span class="block text-sm font-semibold">{{ opt.title }}</span>
            <span
              class="mt-0.5 block text-xs leading-relaxed"
              :class="domainModeModel === opt.value ? 'text-slate-300' : 'text-slate-500'"
            >
              {{ opt.blurb }}
            </span>
          </span>
        </button>
      </div>
    </div>

    <div v-if="domainModeModel === 'student'" class="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
      <label class="block text-xs font-semibold uppercase tracking-wide text-slate-500">
        Surname
        <input
          v-model="studentSurnameModel"
          class="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none ring-slate-900/10 placeholder:text-slate-400 focus:border-slate-400 focus:ring-4"
          placeholder="Mensah"
          autocomplete="family-name"
        />
      </label>
      <p class="mt-3 text-sm leading-relaxed text-slate-600">
        We assign <strong class="font-semibold text-slate-800">{{ studentExample }}</strong>
        during checkout only. Prefilled from your account name when possible.
        If taken: surname1, then surname2. No domain fee.
      </p>
      <p
        v-if="studentPreview"
        class="mt-3 rounded-xl bg-white px-3 py-2 text-sm font-medium text-slate-800 ring-1 ring-slate-200"
      >
        {{ studentPreview }}
      </p>
    </div>

    <div v-else class="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
      <label class="block text-xs font-semibold uppercase tracking-wide text-slate-500">
        {{ domainModeModel === 'register' ? 'Search domain' : 'Your domain' }}
        <div class="mt-2 flex flex-col gap-2 sm:flex-row">
          <input
            v-model="domainLocalModel"
            placeholder="mystudio"
            class="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none ring-slate-900/10 placeholder:text-slate-400 focus:border-slate-400 focus:ring-4"
          />
          <select
            v-model="domainExtModel"
            class="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-slate-400 focus:ring-4 focus:ring-slate-900/10 sm:w-28"
          >
            <option>.online</option>
            <option>.com</option>
            <option>.org</option>
            <option>.net</option>
          </select>
        </div>
      </label>
      <p v-if="domainModeModel === 'register'" class="mt-3 text-sm leading-relaxed text-slate-600">
        .online GHS 50/yr · .com GHS 250/yr · .org GHS 180/yr · .net GHS 200/yr.
        After payment we register it and set ns1 / ns2.ifnotus.space.
      </p>
      <p v-else class="mt-3 text-sm leading-relaxed text-slate-600">
        Use IFNOTUS nameservers or add A records at your registrar when we ask — no domain fee on this invoice.
      </p>
      <button
        v-if="domainModeModel === 'register'"
        type="button"
        class="mt-3 inline-flex items-center justify-center rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-sm font-semibold text-slate-800 transition hover:bg-slate-100"
        @click="emit('checkDomain')"
      >
        Check availability
      </button>
    </div>

    <p
      v-if="domainStatus"
      class="rounded-xl bg-white px-3 py-2 text-sm text-slate-700 ring-1 ring-slate-200"
    >
      {{ domainStatus }}
    </p>
  </div>
</template>
