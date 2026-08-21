<script setup lang="ts">
import SiteHeader from '@/components/site/SiteHeader.vue'
import SitePublicFooter from '@/components/site/SitePublicFooter.vue'
</script>

<template>
  <div class="page">
    <SiteHeader />
    <main class="wrap">
      <p class="eyebrow">Contact</p>
      <h1>Talk to IFNOTUS</h1>
      <p>Accra, Ghana. Hosting invoices are paid by MTN Mobile Money.</p>
      <ul>
        <li>Email: <a href="mailto:support@ifnotus.space">support@ifnotus.space</a></li>
        <li>WhatsApp: <a href="https://wa.me/233541069241">+233 54 106 9241</a></li>
        <li>Hours: Monday–Saturday, 08:00–20:00 GMT</li>
      </ul>
      <p>
        Already a customer?
        <router-link :to="{ name: 'portal-support' }">Open a ticket in your account</router-link>.
      </p>
    </main>
    <SitePublicFooter />
  </div>
</template>

<style scoped>
.page { min-height: 100vh; background: #f6f7f9; }
.wrap { max-width: 40rem; margin: 0 auto; padding: 2rem 1.2rem 4rem; }
.eyebrow { margin: 0; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: #ff6c2c; }
h1 { margin: 0.35rem 0 0.8rem; }
ul { padding-left: 1.1rem; line-height: 1.7; }
a { color: #ff6c2c; }
</style>
