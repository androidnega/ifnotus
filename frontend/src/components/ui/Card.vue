<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    subtitle?: string
    padding?: 'none' | 'sm' | 'md' | 'lg'
    hoverable?: boolean
    as?: string
  }>(),
  { padding: 'md', hoverable: false, as: 'section' },
)

const paddingClass = {
  none: '',
  sm: 'p-3',
  md: 'p-4 md:p-5',
  lg: 'p-5 md:p-6',
}
</script>

<template>
  <component
    :is="as"
    class="rounded-xl border border-surface-border bg-surface-raised shadow-card transition-all duration-300"
    :class="[
      paddingClass[padding],
      hoverable && 'hover:-translate-y-0.5 hover:shadow-elevated',
    ]"
  >
    <header
      v-if="title || $slots.header || $slots.actions"
      class="mb-4 flex items-start justify-between gap-3"
    >
      <div class="min-w-0">
        <slot name="header">
          <h2 v-if="title" class="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {{ title }}
          </h2>
          <p v-if="subtitle" class="mt-0.5 text-xs text-surface-muted">{{ subtitle }}</p>
        </slot>
      </div>
      <div v-if="$slots.actions" class="shrink-0">
        <slot name="actions" />
      </div>
    </header>
    <slot />
  </component>
</template>
