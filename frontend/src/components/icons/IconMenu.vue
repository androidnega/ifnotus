<script setup lang="ts">
import IconBase from './IconBase.vue'
defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <path d="M4 6h16M4 12h16M4 18h16" />
  </IconBase>
</template>
