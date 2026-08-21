<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import PortalShell from '@/components/portal/PortalShell.vue'

const router = useRouter()
const message = ref(
  'Checkout creates an invoice. Pay the IFNOTUS merchant Mobile Money number, then share the transaction ID.',
)
</script>

<template>
  <PortalShell mode="app">
    <div class="card">
      <p class="brand">IFNOTUS</p>
      <h1>Payment</h1>
      <p class="msg">{{ message }}</p>
      <button type="button" class="link" @click="router.push({ name: 'portal-dashboard' })">
        Go to dashboard
      </button>
    </div>
  </PortalShell>
</template>

<style scoped>
.card {
  max-width: 24rem;
  margin: 3rem auto 0;
  text-align: center;
  background: #fff;
  border: 1px solid #e4e8ec;
  border-radius: 0.85rem;
  padding: 2rem 1.5rem;
}
.brand {
  margin: 0;
  font-family: Sora, sans-serif;
  font-size: 1.35rem;
  font-weight: 800;
  letter-spacing: -0.04em;
  color: var(--if-primary, #ff6c2c);
}
h1 {
  margin: 0.5rem 0 0;
  font-family: Sora, sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
}
.msg {
  margin: 0.85rem 0 0;
  color: #5c6670;
  font-size: 0.9rem;
  line-height: 1.5;
}
.link {
  margin-top: 1.25rem;
  border: none;
  background: transparent;
  color: var(--if-primary, #ff6c2c);
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
}
</style>
