<script setup lang="ts">
import { computed } from 'vue'
import { isCustomerCpanelHost, isStaffPanelHost } from '@/lib/platformHosts'

const props = withDefaults(
  defineProps<{
    to?: string | { name: string }
    compact?: boolean
    variant?: 'default' | 'staff'
    /** Light text for dark backgrounds. */
    inverted?: boolean
  }>(),
  { compact: false, variant: 'default', inverted: false },
)

const brandLabel = computed(() => {
  if (props.variant === 'staff' || isStaffPanelHost() || isCustomerCpanelHost()) {
    return 'cPanel'
  }
  return 'IFNOTUS'
})
</script>

<template>
  <component
    :is="to ? 'router-link' : 'span'"
    :to="to"
    class="ds-brand"
    :class="{ 'ds-brand--inverted': inverted }"
    :aria-label="to ? `${brandLabel} home` : undefined"
  >
    <span class="ds-brand-mark" aria-hidden="true">IF</span>
    <span v-if="!compact" class="ds-brand-word">{{ brandLabel }}</span>
  </component>
</template>

<style scoped>
.ds-brand--inverted .ds-brand-word {
  color: #fff;
}
</style>
