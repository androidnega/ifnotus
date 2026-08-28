<script setup lang="ts">
import IconBase from './IconBase.vue'

withDefaults(
  defineProps<{
    size?: number
    iconClass?: string
  }>(),
  { size: 20, iconClass: '' },
)
</script>

<template>
  <IconBase :size="size" :icon-class="iconClass" aria-label="Trash">
    <path
      stroke-linecap="round"
      stroke-linejoin="round"
      d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
    />
  </IconBase>
</template>
