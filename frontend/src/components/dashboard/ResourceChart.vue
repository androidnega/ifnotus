<script setup lang="ts">
import { computed } from 'vue'
import VueApexCharts from 'vue3-apexcharts'
import { useThemeStore } from '@/stores/theme'
import type { ChartData } from '@/types/dashboard'
import Skeleton from '@/components/ui/Skeleton.vue'

const props = defineProps<{
  title: string
  chart: ChartData
  loading?: boolean
  height?: number
  unit?: string
}>()

const theme = useThemeStore()

const options = computed(() => ({
  chart: {
    type: 'area' as const,
    toolbar: { show: false },
    zoom: { enabled: false },
    fontFamily: 'Inter, sans-serif',
    animations: { enabled: true, easing: 'easeinout', speed: 600 },
    background: 'transparent',
  },
  theme: { mode: theme.isDark ? ('dark' as const) : ('light' as const) },
  dataLabels: { enabled: false },
  stroke: { curve: 'smooth' as const, width: 2 },
  fill: {
    type: 'gradient',
    gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.05, stops: [0, 100] },
  },
  colors: props.chart.series.map((s) => s.color),
  grid: {
    borderColor: theme.isDark ? '#1e293b' : '#e2e8f0',
    strokeDashArray: 4,
    padding: { left: 8, right: 8 },
  },
  xaxis: {
    categories: props.chart.categories,
    labels: {
      style: { colors: theme.isDark ? '#94a3b8' : '#64748b', fontSize: '11px' },
      rotate: 0,
      hideOverlappingLabels: true,
    },
    axisBorder: { show: false },
    axisTicks: { show: false },
  },
  yaxis: {
    labels: {
      style: { colors: theme.isDark ? '#94a3b8' : '#64748b', fontSize: '11px' },
      formatter: (v: number) => `${Math.round(v)}${props.unit || ''}`,
    },
  },
  tooltip: {
    theme: (theme.isDark ? 'dark' : 'light') as 'dark' | 'light',
    x: { show: true },
  },
  legend: { show: false },
}))

const series = computed(() =>
  props.chart.series.map((s) => ({ name: s.name, data: s.data })),
)
</script>

<template>
  <div :aria-label="`${title} chart`">
    <Skeleton v-if="loading" :height="`${height || 220}px`" />
    <VueApexCharts
      v-else
      type="area"
      :height="height || 220"
      :options="options"
      :series="series"
    />
  </div>
</template>
