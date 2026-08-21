<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import SiteHeader from '@/components/site/SiteHeader.vue'
import SitePublicFooter from '@/components/site/SitePublicFooter.vue'
import { legalPages, type LegalSlug } from '@/lib/legalPages'

const route = useRoute()
const slug = computed(() => String(route.params.slug || '') as LegalSlug)
const page = computed(() => legalPages[slug.value])
</script>

<template>
  <div class="legal">
    <SiteHeader />
    <main class="wrap">
      <p v-if="!page" class="err">This page was not found.</p>
      <article v-else>
        <p class="eyebrow">IFNOTUS</p>
        <h1>{{ page.title }}</h1>
        <p class="meta">Updated {{ page.updated }}</p>
        <p v-for="(para, i) in page.body" :key="i">{{ para }}</p>
      </article>
    </main>
    <SitePublicFooter />
  </div>
</template>

<style scoped>
.legal { min-height: 100vh; background: #f6f7f9; color: #1a1f24; }
.wrap { max-width: 40rem; margin: 0 auto; padding: 2rem 1.2rem 4rem; }
.eyebrow { margin: 0; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: #ff6c2c; }
h1 { margin: 0.35rem 0 0; font-size: 1.8rem; }
.meta { color: #6b7380; font-size: 0.85rem; }
p { line-height: 1.55; color: #2c333a; }
.err { color: #b42318; }
</style>
