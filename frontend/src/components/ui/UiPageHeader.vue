<script setup lang="ts">
defineProps<{
  eyebrow?: string
  title: string
  lede?: string
}>()
</script>

<template>
  <header class="ds-page-header">
    <p v-if="eyebrow" class="ds-page-eyebrow">{{ eyebrow }}</p>
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <h1 class="ds-page-title">{{ title }}</h1>
        <p v-if="lede" class="ds-page-lede">{{ lede }}</p>
      </div>
      <div v-if="$slots.actions" class="shrink-0">
        <slot name="actions" />
      </div>
    </div>
    <slot />
  </header>
</template>
