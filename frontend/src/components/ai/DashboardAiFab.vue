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
  <div class="dash-ai" :class="{ 'is-open': open }">
    <Transition name="fab-pop">
      <div v-if="open" class="dash-ai-sheet" role="dialog" aria-label="Platform AI Copilot">
        <div class="dash-ai-sheet-header">
          <div class="header-brand">
            <span class="ai-sparkle-badge">
              <i class="fas fa-wand-magic-sparkles" aria-hidden="true" />
            </span>
            <div>
              <h3 class="header-title">AI Copilot</h3>
              <p class="header-subtitle">Ops &amp; infrastructure help</p>
            </div>
          </div>
          <button
            type="button"
            class="ai-close-btn"
            title="Close AI Copilot"
            aria-label="Close"
            @click="open = false"
          >
            <i class="fas fa-times" aria-hidden="true" />
          </button>
        </div>
        <div class="dash-ai-sheet-body">
          <AiAgentPanel surface="dashboard" />
        </div>
      </div>
    </Transition>

    <button
      type="button"
      class="dash-ai-fab"
      :class="{ 'is-open': open }"
      :aria-expanded="open"
      :title="open ? 'Close AI Copilot' : 'Open AI Copilot'"
      :aria-label="open ? 'Close AI Copilot' : 'Open AI Copilot'"
      @click="open = !open"
    >
      <i v-if="open" class="fas fa-xmark" aria-hidden="true" />
      <i v-else class="fas fa-wand-magic-sparkles" aria-hidden="true" />
    </button>
  </div>
</template>

<style scoped>
.dash-ai {
  /* Sit above the page chrome but clear of table pagination (bottom-right). */
  position: fixed;
  right: 0.75rem;
  bottom: 4.75rem;
  z-index: 40;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.55rem;
  pointer-events: none;
}

.dash-ai > * {
  pointer-events: auto;
}

@media (min-width: 900px) {
  .dash-ai {
    right: 1rem;
    bottom: 5.25rem;
  }
}

.dash-ai-sheet {
  width: min(24rem, calc(100vw - 1.5rem));
  max-height: min(70vh, 36rem);
  overflow: hidden;
  border-radius: 0.9rem;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  box-shadow: 0 14px 32px -12px rgba(15, 23, 42, 0.28);
  display: flex;
  flex-direction: column;
}

.dash-ai-sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.65rem 0.85rem;
  background: #0f172a;
  color: #ffffff;
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.ai-sparkle-badge {
  width: 1.55rem;
  height: 1.55rem;
  border-radius: 0.4rem;
  background: #2563eb;
  display: grid;
  place-items: center;
  font-size: 0.7rem;
  color: #ffffff;
}

.header-title {
  margin: 0;
  font-size: 0.8rem;
  font-weight: 650;
  color: #ffffff;
  line-height: 1.2;
}

.header-subtitle {
  margin: 0;
  font-size: 0.68rem;
  color: #94a3b8;
  line-height: 1.2;
}

.ai-close-btn {
  border: none;
  background: rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  width: 1.55rem;
  height: 1.55rem;
  border-radius: 0.35rem;
  display: grid;
  place-items: center;
  cursor: pointer;
  font-size: 0.75rem;
}

.ai-close-btn:hover {
  background: rgba(255, 255, 255, 0.18);
  color: #ffffff;
}

.dash-ai-sheet-body {
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.dash-ai-sheet :deep(.ai-panel) {
  max-height: min(62vh, 30rem);
  border: none;
  box-shadow: none;
}

.dash-ai-sheet :deep(.ai-messages) {
  max-height: min(40vh, 18rem);
}

.dash-ai-fab {
  display: inline-grid;
  place-items: center;
  width: 2.35rem;
  height: 2.35rem;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #ffffff;
  color: #1e293b;
  font-size: 0.85rem;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.12);
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}

.dash-ai-fab:hover {
  background: #f8fafc;
  border-color: #94a3b8;
}

.dash-ai-fab.is-open {
  background: #0f172a;
  border-color: #0f172a;
  color: #ffffff;
}

.fab-pop-enter-active,
.fab-pop-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.fab-pop-enter-from,
.fab-pop-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.98);
}
</style>
