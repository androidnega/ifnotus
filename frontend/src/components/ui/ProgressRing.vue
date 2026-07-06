<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    value: number
    max?: number
    size?: number
    stroke?: number
    label?: string
    color?: string
  }>(),
  { max: 100, size: 120, stroke: 8, color: '#0ea5e9' },
)

const radius = computed(() => (props.size - props.stroke) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)
const offset = computed(() => {
  const pct = Math.min(props.value / props.max, 1)
  return circumference.value * (1 - pct)
})

const tone = computed(() => {
  if (props.value >= 85) return '#10b981'
  if (props.value >= 65) return '#f59e0b'
  return '#ef4444'
})
</script>

<template>
  <div
    class="relative inline-flex items-center justify-center"
    :style="{ width: `${size}px`, height: `${size}px` }"
    role="img"
    :aria-label="label || `${value} out of ${max}`"
  >
    <svg :width="size" :height="size" class="-rotate-90">
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        stroke="currentColor"
        class="text-slate-200 dark:text-slate-700"
        :stroke-width="stroke"
      />
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        :stroke="color || tone"
        :stroke-width="stroke"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="offset"
        class="transition-all duration-700 ease-smooth"
      />
    </svg>
    <div class="absolute inset-0 flex flex-col items-center justify-center">
      <span class="text-2xl font-bold tabular-nums text-slate-900 dark:text-white">{{ value }}</span>
      <span v-if="label" class="text-[10px] uppercase tracking-wider text-surface-muted">{{
        label
      }}</span>
    </div>
  </div>
</template>
