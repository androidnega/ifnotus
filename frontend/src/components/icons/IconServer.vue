<script setup lang="ts">
import IconBase from './IconBase.vue'
defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <rect x="2" y="3" width="20" height="6" rx="1.5" />
    <rect x="2" y="11" width="20" height="10" rx="1.5" />
    <circle cx="6" cy="6" r="1" fill="currentColor" stroke="none" />
    <circle cx="6" cy="16" r="1" fill="currentColor" stroke="none" />
  </IconBase>
</template>
