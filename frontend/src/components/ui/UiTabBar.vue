<script setup lang="ts">
export type UiTabItem = {
  id: string
  label: string
  disabled?: boolean
}

withDefaults(
  defineProps<{
    items: UiTabItem[]
    modelValue: string
    variant?: 'pill' | 'flat' | 'sidebar'
    ariaLabel?: string
  }>(),
  { variant: 'pill', ariaLabel: 'Sections' },
)

const emit = defineEmits<{
  'update:modelValue': [id: string]
}>()

function select(item: UiTabItem) {
  if (item.disabled) return
  emit('update:modelValue', item.id)
}
</script>

<template>
  <nav
    class="ds-tabbar"
    :class="{
      'ds-tabbar--flat': variant === 'flat',
      'ds-tabbar--sidebar': variant === 'sidebar',
    }"
    :aria-label="ariaLabel"
  >
    <button
      v-for="item in items"
      :key="item.id"
      type="button"
      class="ds-tab"
      :class="{ on: modelValue === item.id, off: item.disabled }"
      :disabled="item.disabled"
      :aria-current="modelValue === item.id ? 'page' : undefined"
      @click="select(item)"
    >
      {{ item.label }}
    </button>
  </nav>
</template>
