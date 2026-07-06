<script setup lang="ts">
import { computed } from 'vue'

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'neutral'

const props = withDefaults(
  defineProps<{
    variant?: BadgeVariant
    dot?: boolean
    size?: 'sm' | 'md'
  }>(),
  { variant: 'default', dot: false, size: 'sm' },
)

const classes = computed(() => {
  const base = 'inline-flex items-center gap-1.5 rounded-full font-medium'
  const sizes = {
    sm: 'px-2 py-0.5 text-[11px]',
    md: 'px-2.5 py-1 text-xs',
  }
  const variants: Record<BadgeVariant, string> = {
    default: 'bg-brand-500/10 text-brand-700 dark:text-brand-300',
    success: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    warning: 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
    danger: 'bg-red-500/10 text-red-700 dark:text-red-300',
    info: 'bg-sky-500/10 text-sky-700 dark:text-sky-300',
    neutral: 'bg-slate-500/10 text-slate-600 dark:text-slate-300',
  }
  return [base, sizes[props.size], variants[props.variant]]
})

const dotClass = computed(() => {
  const map: Record<BadgeVariant, string> = {
    default: 'bg-brand-500',
    success: 'bg-emerald-500',
    warning: 'bg-amber-500',
    danger: 'bg-red-500',
    info: 'bg-sky-500',
    neutral: 'bg-slate-400',
  }
  return map[props.variant]
})
</script>

<template>
  <span :class="classes">
    <span v-if="dot" class="h-1.5 w-1.5 rounded-full" :class="dotClass" aria-hidden="true" />
    <slot />
  </span>
</template>
