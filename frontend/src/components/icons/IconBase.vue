<script setup lang="ts">
withDefaults(
  defineProps<{ size?: number; iconClass?: string }>(),
  { size: 20, iconClass: '' },
)
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    :class="iconClass"
    aria-hidden="true"
  >
    <slot />
  </svg>
</template>
