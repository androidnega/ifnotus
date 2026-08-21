<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  busy?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  cancel: []
  confirm: [password: string]
}>()

const password = ref('')
const acknowledged = ref(false)
const inputEl = ref<HTMLInputElement | null>(null)

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    password.value = ''
    acknowledged.value = false
    await nextTick()
    inputEl.value?.focus()
  },
)

onMounted(() => {
  if (props.open) inputEl.value?.focus()
})

function submit() {
  if (!acknowledged.value || !password.value.trim() || props.busy) return
  emit('confirm', password.value)
}
</script>

<template>
  <div v-if="open" class="modal-root" role="dialog" aria-modal="true">
    <button type="button" class="backdrop" aria-label="Close" @click="emit('cancel')" />
    <div class="panel">
      <h2>{{ title }}</h2>
      <p class="desc">{{ description }}</p>
      <label class="ack">
        <input v-model="acknowledged" type="checkbox" />
        <span>Yes, I am sure. This cannot be undone.</span>
      </label>
      <label class="pw">
        <span>Dashboard admin password</span>
        <input
          ref="inputEl"
          v-model="password"
          type="password"
          autocomplete="current-password"
          placeholder="Enter your login password"
          @keydown.enter.prevent="submit"
        />
      </label>
      <p v-if="error" class="err">{{ error }}</p>
      <div class="actions">
        <button type="button" class="btn ghost" :disabled="busy" @click="emit('cancel')">Cancel</button>
        <button
          type="button"
          class="btn danger"
          :disabled="busy || !acknowledged || !password.trim()"
          @click="submit"
        >
          {{ busy ? 'Working…' : (confirmLabel || 'Drop database') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-root {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 1rem;
}
.backdrop {
  position: absolute;
  inset: 0;
  border: 0;
  background: rgb(2 6 23 / 0.55);
  backdrop-filter: blur(4px);
}
.panel {
  position: relative;
  z-index: 1;
  width: min(28rem, 100%);
  border-radius: 1rem;
  border: 1px solid rgb(148 163 184 / 0.25);
  background: #0f172a;
  color: #e2e8f0;
  padding: 1.15rem 1.2rem 1.1rem;
  box-shadow: 0 24px 60px rgb(0 0 0 / 0.35);
}
.panel h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
}
.desc {
  margin: 0.55rem 0 0;
  font-size: 0.85rem;
  line-height: 1.45;
  color: #94a3b8;
}
.ack,
.pw {
  display: flex;
  gap: 0.55rem;
  margin-top: 1rem;
  font-size: 0.82rem;
}
.ack {
  align-items: flex-start;
}
.ack input {
  margin-top: 0.15rem;
}
.pw {
  flex-direction: column;
  gap: 0.35rem;
}
.pw input {
  border-radius: 0.65rem;
  border: 1px solid rgb(148 163 184 / 0.28);
  background: #111827;
  color: inherit;
  padding: 0.65rem 0.75rem;
  font-size: 0.9rem;
}
.err {
  margin: 0.75rem 0 0;
  color: #fca5a5;
  font-size: 0.8rem;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.55rem;
  margin-top: 1.1rem;
}
.btn {
  border-radius: 0.65rem;
  border: 1px solid transparent;
  padding: 0.5rem 0.85rem;
  font-size: 0.82rem;
  font-weight: 600;
}
.btn:disabled {
  opacity: 0.5;
}
.btn.ghost {
  border-color: rgb(148 163 184 / 0.28);
  background: transparent;
  color: inherit;
}
.btn.danger {
  background: #dc2626;
  color: white;
}
</style>
