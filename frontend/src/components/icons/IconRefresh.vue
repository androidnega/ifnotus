<script setup lang="ts">
import IconBase from './IconBase.vue'
defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <path d="M21 12a9 9 0 1 1-9-9" />
    <path d="M21 3v6h-6" />
  </IconBase>
</template>
