<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    values: number[]
    color?: string
    width?: number
    height?: number
  }>(),
  { color: '#3b82f6', width: 88, height: 28 },
)

const d = computed(() => {
  const vals = props.values.length ? props.values : [0, 0]
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = max - min || 1
  const w = props.width
  const h = props.height
  return vals
    .map((v, i) => {
      const x = (i / Math.max(vals.length - 1, 1)) * w
      const y = h - ((v - min) / span) * (h - 4) - 2
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
})
</script>

<template>
  <svg
    :width="width"
    :height="height"
    :viewBox="`0 0 ${width} ${height}`"
    fill="none"
    aria-hidden="true"
  >
    <path :d="d" :stroke="color" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
</template>
