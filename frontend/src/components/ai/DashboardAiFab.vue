<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import AiAgentPanel from '@/components/ai/AiAgentPanel.vue'

const open = ref(false)

function onKey(ev: KeyboardEvent) {
  if (ev.key === 'Escape') open.value = false
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="dash-ai">
    <Transition name="fab-pop">
      <div v-if="open" class="dash-ai-sheet" role="dialog" aria-label="Server AI overview">
        <AiAgentPanel surface="dashboard" />
      </div>
    </Transition>

    <button
      type="button"
      class="dash-ai-fab"
      :class="{ 'is-open': open }"
      :aria-expanded="open"
      :title="open ? 'Close AI' : 'Ask AI about this server'"
      @click="open = !open"
    >
      <span class="fab-glow" aria-hidden="true" />
      <span class="fab-label">{{ open ? 'Close' : 'AI' }}</span>
    </button>
  </div>
</template>

<style scoped>
.dash-ai {
  position: fixed;
  right: 1.1rem;
  bottom: 1.1rem;
  z-index: 40;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.75rem;
}
.dash-ai-sheet {
  width: min(24rem, calc(100vw - 1.5rem));
  max-height: min(70vh, 36rem);
  overflow: hidden;
  border-radius: 1rem;
  box-shadow: 0 18px 50px rgb(15 23 42 / 0.28);
}
.dash-ai-sheet :deep(.ai-panel) {
  max-height: min(70vh, 36rem);
}
.dash-ai-sheet :deep(.ai-messages) {
  max-height: min(42vh, 20rem);
}
.dash-ai-fab {
  position: relative;
  display: inline-flex;
  height: 3.25rem;
  min-width: 3.25rem;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 0;
  border-radius: 999px;
  background: linear-gradient(145deg, #0f766e, #115e59);
  padding: 0 1.1rem;
  color: white;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  box-shadow: 0 10px 28px rgb(15 118 110 / 0.35);
  transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
}
.dash-ai-fab:hover {
  transform: translateY(-1px);
  box-shadow: 0 14px 32px rgb(15 118 110 / 0.42);
}
.dash-ai-fab.is-open {
  background: #334155;
  box-shadow: 0 10px 24px rgb(15 23 42 / 0.28);
}
.fab-glow {
  position: absolute;
  inset: -40%;
  background: radial-gradient(circle at 30% 30%, rgb(255 255 255 / 0.28), transparent 45%);
  pointer-events: none;
}
.fab-label { position: relative; }
.fab-pop-enter-active,
.fab-pop-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.fab-pop-enter-from,
.fab-pop-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.98);
}
</style>
