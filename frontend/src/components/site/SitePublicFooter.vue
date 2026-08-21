<template>
  <footer class="foot">
    <nav>
      <router-link :to="{ name: 'legal', params: { slug: 'pay' } }">How to pay</router-link>
      <router-link :to="{ name: 'legal', params: { slug: 'nameservers' } }">Nameservers</router-link>
      <router-link :to="{ name: 'contact' }">Contact</router-link>
      <router-link :to="{ name: 'status' }">Status</router-link>
      <router-link :to="{ name: 'legal', params: { slug: 'terms' } }">Terms</router-link>
      <router-link :to="{ name: 'legal', params: { slug: 'privacy' } }">Privacy</router-link>
      <router-link :to="{ name: 'legal', params: { slug: 'refunds' } }">Refunds</router-link>
      <router-link :to="{ name: 'legal', params: { slug: 'aup' } }">Acceptable use</router-link>
    </nav>
    <p>IFNOTUS · Accra · ns1.ifnotus.space · ns2.ifnotus.space</p>
  </footer>
</template>

<style scoped>
.foot {
  padding: 2rem 1.2rem 2.5rem;
  border-top: 1px solid #e4e8ec;
  background: #fff;
  text-align: center;
  color: #5c6670;
  font-size: 0.82rem;
}
nav { display: flex; flex-wrap: wrap; gap: 0.75rem 1rem; justify-content: center; margin-bottom: 0.75rem; }
a { color: #2c333a; text-decoration: none; }
a:hover { color: #ff6c2c; }
</style>
