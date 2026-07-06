<script setup lang="ts">
import IconBase from './IconBase.vue'
defineProps<{ size?: number; iconClass?: string }>()
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass">
    <path d="M4 7h5l2 2h9v10H4z" />
    <path d="M4 7v12h16V9h-9l-2-2H4z" />
  </IconBase>
</template>
