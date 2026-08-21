<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    label: string
    value: number
    suffix?: string
    color?: string
  }>(),
  { suffix: '%', color: '#2563eb' },
)

const clamped = computed(() => Math.max(0, Math.min(100, Number(props.value) || 0)))
</script>

<template>
  <div class="gauge">
    <svg viewBox="0 0 88 56" class="arc" aria-hidden="true">
      <path
        d="M 8 48 A 36 36 0 0 1 80 48"
        fill="none"
        stroke="currentColor"
        class="track"
        stroke-width="8"
        stroke-linecap="round"
      />
      <path
        d="M 8 48 A 36 36 0 0 1 80 48"
        fill="none"
        :stroke="color"
        stroke-width="8"
        stroke-linecap="round"
        :stroke-dasharray="`${clamped} 100`"
        pathLength="100"
      />
    </svg>
    <p class="val">{{ Math.round(clamped) }}{{ suffix }}</p>
    <p class="lab">{{ label }}</p>
  </div>
</template>

<style scoped>
.gauge {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 4.5rem;
}
.arc {
  width: 5.5rem;
  height: 3.5rem;
  color: #e8edf3;
}
:global(.dark) .arc {
  color: #1e293b;
}
.val {
  margin: -0.15rem 0 0;
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: #0f172a;
}
:global(.dark) .val {
  color: #f8fafc;
}
.lab {
  margin: 0.1rem 0 0;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #64748b;
}
</style>
