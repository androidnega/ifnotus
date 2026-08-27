<script setup lang="ts">
withDefaults(
  defineProps<{
    tone?: 'ok' | 'err' | 'warn' | 'info'
  }>(),
  { tone: 'info' },
)
</script>

<template>
  <p class="ds-alert" :class="`ds-alert--${tone}`" role="status">
    <slot />
  </p>
</template>
