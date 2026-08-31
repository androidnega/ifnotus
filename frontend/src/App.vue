<script setup lang="ts">
import { RouterView } from 'vue-router'
import { useInactivityTimeout } from '@/composables/useInactivityTimeout'

// Enforce 20-minute inactivity session expiration across panels
useInactivityTimeout()
</script>

<template>
  <RouterView />
</template>
