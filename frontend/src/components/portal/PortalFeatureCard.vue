<script setup lang="ts">
defineProps<{
  title: string
  description?: string
  meta?: string
  active?: boolean
  clickable?: boolean
}>()

defineEmits<{ click: [] }>()
</script>

<template>
  <component
    :is="clickable ? 'button' : 'div'"
    type="button"
    class="p-card"
    :class="{ clickable, active }"
    @click="clickable ? $emit('click') : undefined"
  >
    <div class="p-row">
      <span class="p-icon"><slot name="icon" /></span>
      <div>
        <p class="p-title">{{ title }}</p>
        <p v-if="description" class="p-desc">{{ description }}</p>
        <p v-if="meta" class="p-meta">{{ meta }}</p>
        <slot />
      </div>
    </div>
  </component>
</template>
