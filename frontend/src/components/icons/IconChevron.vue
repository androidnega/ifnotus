<script setup lang="ts">
import IconBase from './IconBase.vue'
defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <path d="M3 12h18" />
    <path d="m9 6 6 6-6 6" />
  </IconBase>
</template>
