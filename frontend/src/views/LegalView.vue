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
  <div class="legal-page">
    <SiteHeader />
    <main class="wrap">
      <div class="doc-card">
        <p v-if="!page" class="err">This document was not found.</p>
        <article v-else>
          <p class="eyebrow">IFNOTUS Legal & Policy</p>
          <h1>{{ page.title }}</h1>
          <p class="meta">Last updated: {{ page.updated }}</p>
          <div class="doc-body">
            <p v-for="(para, i) in page.body" :key="i">{{ para }}</p>
          </div>
        </article>
      </div>
    </main>
    <SitePublicFooter />
  </div>
</template>

<style scoped>
.legal-page {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
  color: #1a1f24;
  font-family: 'Figtree', ui-sans-serif, system-ui, sans-serif;
}
.wrap {
  flex: 1 0 auto;
  max-width: 50rem;
  width: 100%;
  margin: 0 auto;
  padding: 2.5rem 1.25rem 4rem;
  box-sizing: border-box;
}
.doc-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  padding: clamp(1.5rem, 4vw, 2.75rem);
  box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.04);
}
.eyebrow {
  margin: 0;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #ff6c2c;
}
h1 {
  margin: 0.4rem 0 0.5rem;
  font-size: clamp(1.6rem, 3.5vw, 2.2rem);
  font-weight: 800;
  color: #0f172a;
}
.meta {
  color: #64748b;
  font-size: 0.85rem;
  margin: 0 0 1.75rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid #f1f5f9;
}
.doc-body p {
  line-height: 1.7;
  color: #334155;
  font-size: 0.95rem;
  margin: 0 0 1.15rem;
}
.err {
  color: #b42318;
  font-weight: 600;
}
</style>
