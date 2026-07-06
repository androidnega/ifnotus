<script setup lang="ts">
defineProps<{
  title?: string
  message?: string
}>()
</script>

<template>
  <div class="flex flex-col items-center justify-center py-10 text-center" role="status">
    <div
      class="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 dark:bg-slate-800"
    >
      <slot name="icon" />
    </div>
    <p class="text-sm font-medium text-slate-700 dark:text-slate-200">
      {{ title || 'No data yet' }}
    </p>
    <p v-if="message" class="mt-1 max-w-sm text-xs text-surface-muted">{{ message }}</p>
    <slot />
  </div>
</template>
