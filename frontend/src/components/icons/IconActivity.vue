<script setup lang="ts">
import IconBase from './IconBase.vue'
defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
  </IconBase>
</template>
