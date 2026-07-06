<script setup lang="ts">
import IconBase from './IconBase.vue'
defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <rect x="3" y="6" width="18" height="13" rx="2" />
    <path d="m3 8 9 6 9-6" />
  </IconBase>
</template>
