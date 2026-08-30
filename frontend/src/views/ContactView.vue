<script setup lang="ts">
import SiteHeader from '@/components/site/SiteHeader.vue'
import SitePublicFooter from '@/components/site/SitePublicFooter.vue'
</script>

<template>
  <div class="page">
    <SiteHeader active="contact" />
    <main class="wrap">
      <div class="contact-card">
        <p class="eyebrow">Contact & Support</p>
        <h1>Talk to IFNOTUS</h1>
        <p class="lede">
          We’re based in Accra, Ghana. We assist businesses, agencies, and developers with modern web hosting, domain provisioning, databases, and deployment.
        </p>

        <div class="contact-grid">
          <div class="channel-card">
            <div class="icon-bubble"><i class="fa-solid fa-envelope" /></div>
            <div class="channel-info">
              <h3>Direct Email</h3>
              <p>For inquiries, billing, and technical assistance.</p>
              <a href="mailto:support@ifnotus.space">support@ifnotus.space</a>
            </div>
          </div>

          <div class="channel-card">
            <div class="icon-bubble whatsapp"><i class="fa-brands fa-whatsapp" /></div>
            <div class="channel-info">
              <h3>WhatsApp Chat</h3>
              <p>Fast responses during active operations.</p>
              <a href="https://wa.me/233541069241" target="_blank" rel="noopener noreferrer">+233 54 106 9241</a>
            </div>
          </div>

          <div class="channel-card">
            <div class="icon-bubble time"><i class="fa-solid fa-clock" /></div>
            <div class="channel-info">
              <h3>Support Hours</h3>
              <p>Monday–Saturday: 08:00 – 20:00 GMT</p>
              <span class="badge-active">Active Operations</span>
            </div>
          </div>

          <div class="channel-card">
            <div class="icon-bubble ticket"><i class="fa-solid fa-headset" /></div>
            <div class="channel-info">
              <h3>Customer Portal</h3>
              <p>Existing tenant? Log in to open a prioritized ticket.</p>
              <router-link :to="{ name: 'portal-support' }">Open Support Ticket →</router-link>
            </div>
          </div>
        </div>

        <div class="payment-note">
          <div class="momo-tag"><i class="fa-solid fa-mobile-screen" /> Mobile Money</div>
          <p>
            Hosting payments and renewals are completed instantly via MTN MoMo, Telecel Cash, or AirtelTigo with automated invoice references.
          </p>
        </div>
      </div>
    </main>
    <SitePublicFooter />
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
  color: #1e293b;
  font-family: 'Figtree', ui-sans-serif, system-ui, sans-serif;
}
.wrap {
  flex: 1 0 auto;
  max-width: 52rem;
  width: 100%;
  margin: 0 auto;
  padding: 2.5rem 1.25rem 4rem;
  box-sizing: border-box;
}
.contact-card {
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
  margin: 0.4rem 0 0.8rem;
  font-size: clamp(1.6rem, 3.5vw, 2.2rem);
  font-weight: 800;
  color: #0f172a;
}
.lede {
  margin: 0 0 2rem;
  font-size: 1rem;
  line-height: 1.6;
  color: #475569;
}
.contact-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
  gap: 1.2rem;
  margin-bottom: 2rem;
}
.channel-card {
  display: flex;
  gap: 1rem;
  padding: 1.1rem;
  border: 1px solid #eef2f6;
  border-radius: 0.75rem;
  background: #fafbfc;
  transition: transform 0.15s ease, border-color 0.15s ease;
}
.channel-card:hover {
  transform: translateY(-2px);
  border-color: #cbd5e1;
}
.icon-bubble {
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 0.65rem;
  background: rgba(255, 108, 44, 0.12);
  color: #ff6c2c;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.15rem;
  flex-shrink: 0;
}
.icon-bubble.whatsapp {
  background: rgba(34, 197, 94, 0.12);
  color: #16a34a;
}
.icon-bubble.time {
  background: rgba(59, 130, 246, 0.12);
  color: #2563eb;
}
.icon-bubble.ticket {
  background: rgba(168, 85, 247, 0.12);
  color: #9333ea;
}
.channel-info h3 {
  margin: 0 0 0.25rem;
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}
.channel-info p {
  margin: 0 0 0.35rem;
  font-size: 0.84rem;
  color: #64748b;
  line-height: 1.45;
}
.channel-info a {
  font-size: 0.88rem;
  font-weight: 600;
  color: #ff6c2c;
  text-decoration: none;
}
.channel-info a:hover {
  text-decoration: underline;
}
.badge-active {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  color: #059669;
  background: #ecfdf5;
  padding: 0.15rem 0.5rem;
  border-radius: 1rem;
}
.payment-note {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1rem 1.25rem;
  border-radius: 0.75rem;
  background: #fff7ed;
  border: 1px solid #ffedd5;
}
.momo-tag {
  font-size: 0.8rem;
  font-weight: 700;
  color: #c2410c;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.payment-note p {
  margin: 0;
  font-size: 0.85rem;
  color: #9a3412;
  line-height: 1.5;
}
</style>
