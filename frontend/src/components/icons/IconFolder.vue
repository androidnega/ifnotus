<script setup lang="ts">
import IconBase from './IconBase.vue'

withDefaults(
  defineProps<{
    size?: number
    iconClass?: string
    /** Classic Windows Explorer yellow folder */
    variant?: 'default' | 'windows' | 'unix'
  }>(),
  { size: 20, iconClass: '', variant: 'default' },
)
</script>

<template>
  <svg
    v-if="variant === 'windows'"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    :class="iconClass"
    aria-hidden="true"
  >
    <path fill="#E8B931" d="M3.5 7.5h6.2l1.6 1.7H20.5v9.3a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5V7.5z" />
    <path fill="#F5D76E" d="M3.5 7.5h6.2l1.3 1.4H3.5V7.5z" />
    <path fill="#C9921A" opacity="0.35" d="M3.5 16.5h17v1.5A1.5 1.5 0 0 1 19 19.5H5A1.5 1.5 0 0 1 3.5 18v-1.5z" />
  </svg>
  <svg
    v-else-if="variant === 'unix'"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    :class="iconClass"
    aria-hidden="true"
  >
    <path d="M4 8h5l2 2h9v9H4z" />
    <path d="M4 8V6h5l1.5 1.5" />
  </svg>
  <IconBase v-else :size="size" :icon-class="iconClass">
    <path d="M4 7h5l2 2h9v10H4z" />
    <path d="M4 7v12h16V9h-9l-2-2H4z" />
  </IconBase>
</template>
