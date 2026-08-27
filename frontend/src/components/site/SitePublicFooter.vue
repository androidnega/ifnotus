<template>
  <footer class="foot">
    <nav aria-label="Site legal">
      <router-link :to="{ name: 'legal', params: { slug: 'pay' } }">How to pay</router-link>
      <router-link :to="{ name: 'legal', params: { slug: 'nameservers' } }">Nameservers</router-link>
      <router-link :to="{ name: 'contact' }">Contact</router-link>
      <router-link :to="{ name: 'status' }">Status</router-link>
      <router-link :to="{ name: 'legal', params: { slug: 'terms' } }">Terms</router-link>
      <router-link :to="{ name: 'legal', params: { slug: 'privacy' } }">Privacy</router-link>
      <router-link :to="{ name: 'legal', params: { slug: 'refunds' } }">Refunds</router-link>
      <router-link :to="{ name: 'legal', params: { slug: 'aup' } }">Acceptable use</router-link>
    </nav>
    <div class="meta-row">
      <p class="meta">© {{ year }} IFNOTUS · Accra</p>
      <p class="accept" aria-label="Accepted Mobile Money networks">
        <span class="accept-label">We accept</span>
        <span class="oval mtn" title="MTN MoMo">MTN</span>
        <span class="oval telecel" title="Telecel Cash">Telecel</span>
        <span class="oval airtel" title="AirtelTigo Money">AirtelTigo</span>
      </p>
    </div>
  </footer>
</template>

<script setup lang="ts">
const year = new Date().getFullYear()
</script>

<style scoped>
.foot {
  padding: 1.5rem 1.2rem 2rem;
  border-top: 1px solid var(--if-border, #e4e8ec);
  background: var(--if-surface, #fff);
  text-align: center;
  color: var(--if-muted, #5c6670);
  font-size: 0.82rem;
}
nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1rem;
  justify-content: center;
  margin-bottom: 0.85rem;
}
a {
  color: var(--if-ink, #2c333a);
  text-decoration: none;
}
a:hover {
  color: var(--if-primary, #ff6c2c);
}
.meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.55rem 1rem;
}
.meta {
  margin: 0;
}
.accept {
  margin: 0;
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
}
.accept-label {
  font-size: 0.75rem;
  color: var(--if-muted, #6b7280);
}
.oval {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 2.85rem;
  height: 1.35rem;
  padding: 0 0.55rem;
  border-radius: 50%;
  font-family: var(--ds-font-display, 'Sora', Segoe UI, sans-serif);
  font-size: 0.58rem;
  font-weight: 800;
  letter-spacing: 0.01em;
  line-height: 1;
  user-select: none;
  border: 1px solid transparent;
}
.oval.mtn {
  background: #ffcc00;
  color: #1a1a1a;
  border-color: #e6a800;
}
.oval.telecel {
  background: #e11d2e;
  color: #fff;
  border-color: #b91c1c;
}
.oval.airtel {
  background: linear-gradient(90deg, #1d4ed8 0%, #1d4ed8 42%, #ed1c24 42%, #ed1c24 100%);
  color: #fff;
  border-color: #1e3a8a;
  min-width: 3.6rem;
}
</style>
