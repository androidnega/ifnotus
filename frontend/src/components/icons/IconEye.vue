<script setup lang="ts">
import IconBase from './IconBase.vue'
defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
    <circle cx="12" cy="12" r="3" />
  </IconBase>
</template>
