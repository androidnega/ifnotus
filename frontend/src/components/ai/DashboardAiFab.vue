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
      <div v-if="open" class="dash-ai-sheet" role="dialog" aria-label="Platform AI Copilot">
        <div class="dash-ai-sheet-header">
          <div class="header-brand">
            <span class="ai-sparkle-badge">
              <i class="fas fa-wand-magic-sparkles" aria-hidden="true" />
            </span>
            <div>
              <h3 class="header-title">Platform AI Copilot</h3>
              <p class="header-subtitle">Infrastructure &amp; Operations Intelligence</p>
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
      :title="open ? 'Close AI Copilot' : 'Open Platform AI Copilot'"
      @click="open = !open"
    >
      <span class="fab-pulse-ring" aria-hidden="true" />
      <span class="fab-icon-wrap">
        <i v-if="open" class="fas fa-xmark" aria-hidden="true" />
        <i v-else class="fas fa-wand-magic-sparkles" aria-hidden="true" />
      </span>
      <span class="fab-label">{{ open ? 'Close' : 'AI Copilot' }}</span>
    </button>
  </div>
</template>

<style scoped>
.dash-ai {
  position: fixed;
  right: 1.25rem;
  bottom: 1.25rem;
  z-index: 50;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.85rem;
}

.dash-ai-sheet {
  width: min(26rem, calc(100vw - 2rem));
  max-height: min(76vh, 40rem);
  overflow: hidden;
  border-radius: 1.15rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  box-shadow: 0 20px 45px -10px rgba(15, 23, 42, 0.28), 0 0 0 1px rgba(15, 23, 42, 0.05);
  display: flex;
  flex-direction: column;
}

.dash-ai-sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 1.15rem;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
  color: #ffffff;
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.ai-sparkle-badge {
  width: 2rem;
  height: 2rem;
  border-radius: 0.55rem;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  display: grid;
  place-items: center;
  font-size: 0.85rem;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.35);
}

.header-title {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 700;
  color: #ffffff;
  line-height: 1.2;
}

.header-subtitle {
  margin: 0;
  font-size: 0.72rem;
  color: #94a3b8;
  line-height: 1.2;
}

.ai-close-btn {
  border: none;
  background: rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 0.4rem;
  display: grid;
  place-items: center;
  cursor: pointer;
  font-size: 0.85rem;
  transition: all 0.15s ease;
}

.ai-close-btn:hover {
  background: rgba(255, 255, 255, 0.2);
  color: #ffffff;
}

.dash-ai-sheet-body {
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.dash-ai-sheet :deep(.ai-panel) {
  max-height: min(68vh, 34rem);
  border: none;
  box-shadow: none;
}

.dash-ai-sheet :deep(.ai-messages) {
  max-height: min(44vh, 22rem);
}

.dash-ai-fab {
  position: relative;
  display: inline-flex;
  height: 2.85rem;
  align-items: center;
  gap: 0.55rem;
  padding: 0 1.15rem;
  border: none;
  border-radius: 999px;
  background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 55%, #7c3aed 100%);
  color: #ffffff;
  font-family: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  cursor: pointer;
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.38), 0 2px 6px rgba(15, 23, 42, 0.12);
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.dash-ai-fab:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 12px 30px rgba(37, 99, 235, 0.48), 0 4px 10px rgba(15, 23, 42, 0.18);
}

.dash-ai-fab.is-open {
  background: #334155;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.25);
  transform: none;
}

.fab-icon-wrap {
  display: grid;
  place-items: center;
  font-size: 0.95rem;
}

.fab-pulse-ring {
  position: absolute;
  inset: -3px;
  border-radius: 999px;
  border: 2px solid rgba(124, 58, 237, 0.4);
  pointer-events: none;
  animation: fab-pulse 2.8s infinite ease-out;
}

.dash-ai-fab.is-open .fab-pulse-ring {
  display: none;
}

@keyframes fab-pulse {
  0% { transform: scale(0.96); opacity: 0.8; }
  50% { transform: scale(1.06); opacity: 0.2; }
  100% { transform: scale(1.12); opacity: 0; }
}

.fab-label {
  position: relative;
  font-weight: 700;
}

.fab-pop-enter-active,
.fab-pop-leave-active {
  transition: opacity 0.2s ease, transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.fab-pop-enter-from,
.fab-pop-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(0.96);
}
</style>
