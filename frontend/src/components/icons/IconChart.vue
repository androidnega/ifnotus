<script setup lang="ts">
import IconBase from './IconBase.vue'
defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <path d="M3 3v18h18" />
    <path d="M7 16l4-8 4 5 4-9" />
  </IconBase>
</template>
