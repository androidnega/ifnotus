import { createApp } from 'vue'
import { createPinia } from 'pinia'
import VueApexCharts from 'vue3-apexcharts'
import App from './App.vue'
import router from './router'
import { useSiteTheme, hydrateThemeFromCache } from './composables/useSiteTheme'
import './assets/main.css'
import './assets/design-system.css'
import './assets/portal.css'
import './assets/control.css'
import '@fortawesome/fontawesome-free/css/all.min.css'

const isApple =
  typeof navigator !== 'undefined' &&
  (/Mac|iPhone|iPad|iPod/i.test(navigator.platform) || /Mac OS X/i.test(navigator.userAgent))
if (!isApple) {
  document.documentElement.classList.add('os-non-mac')
}

hydrateThemeFromCache()

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.component('VueApexCharts', VueApexCharts)

app.mount('#app')

// Apply staff-managed brand colors as soon as possible.
void useSiteTheme().load()
