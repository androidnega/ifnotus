<script setup lang="ts">
withDefaults(
  defineProps<{
    to?: string | { name: string }
    compact?: boolean
    variant?: 'default' | 'staff'
    /** Light text for dark backgrounds. */
    inverted?: boolean
  }>(),
  { compact: false, variant: 'default', inverted: false },
)
</script>

<template>
  <component
    :is="to ? 'router-link' : 'span'"
    :to="to"
    class="ds-brand"
    :class="{ 'ds-brand--inverted': inverted }"
    :aria-label="to ? 'IFNOTUS home' : undefined"
  >
    <span class="ds-brand-mark" aria-hidden="true">IF</span>
    <span v-if="!compact" class="ds-brand-word">IFNOTUS</span>
  </component>
</template>

<style scoped>
.ds-brand--inverted .ds-brand-word {
  color: #fff;
}
</style>
