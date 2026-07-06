<script setup lang="ts">
withDefaults(
  defineProps<{
    width?: string
    height?: string
    rounded?: boolean
  }>(),
  { width: '100%', height: '1rem', rounded: true },
)
</script>

<template>
  <div
    class="animate-pulse bg-slate-200 dark:bg-slate-700/60"
    :class="rounded ? 'rounded-md' : ''"
    :style="{ width, height }"
    aria-hidden="true"
  />
</template>
