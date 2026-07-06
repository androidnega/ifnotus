<script setup lang="ts">
import IconBase from './IconBase.vue'
defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <path d="M12 3v2" />
    <path d="M12 19v2" />
    <path d="M5 12H3" />
    <path d="M21 12h-2" />
    <circle cx="12" cy="12" r="4" />
  </IconBase>
</template>
