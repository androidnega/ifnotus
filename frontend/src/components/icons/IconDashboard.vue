<script setup lang="ts">
import IconBase from './IconBase.vue'

defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <rect x="3" y="3" width="7" height="7" rx="1" />
    <rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
    <rect x="14" y="14" width="7" height="7" rx="1" />
  </IconBase>
</template>
