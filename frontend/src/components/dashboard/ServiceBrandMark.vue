<script setup lang="ts">
withDefaults(
  defineProps<{
    name: string
    size?: number
  }>(),
  { size: 36 },
)
</script>

<template>
  <!-- Official-looking marks (simplified brand glyphs, not letter placeholders). -->
  <svg
    v-if="name === 'nginx'"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    aria-hidden="true"
  >
    <rect width="48" height="48" rx="10" fill="#009639" />
    <path
      fill="#fff"
      d="M14.2 10.5h6.4l13.2 18.4V10.5h6.1v27H33.6L20.4 19.2v18.3h-6.2z"
    />
  </svg>

  <svg
    v-else-if="name === 'apache'"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    aria-hidden="true"
  >
    <rect width="48" height="48" rx="10" fill="#fff" />
    <path fill="#D22128" d="M24 8c-1.2 6.4-4.8 11.2-9.2 15.2 3.4-1 6.2-1.2 9.2-1.2s5.8.2 9.2 1.2C28.8 19.2 25.2 14.4 24 8z" />
    <path fill="#282661" d="M16.2 25.6c2.4 4.8 5.2 8.8 7.8 14.4 2.6-5.6 5.4-9.6 7.8-14.4-2.4.6-5 .8-7.8.8s-5.4-.2-7.8-.8z" />
    <path fill="#F5B52E" d="M24 8c.4 4.2 2.2 8 5.2 11.4C27.2 17 25.4 13.4 24 8z" />
  </svg>

  <svg
    v-else-if="name === 'mysql'"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    aria-hidden="true"
  >
    <rect width="48" height="48" rx="10" fill="#00758F" />
    <path
      fill="#F29111"
      d="M34.4 31.2c-1.6.9-3.6 1.5-5.1 1.8-.4.1-.8-.2-.7-.6.3-1.1.6-2.2.5-3.3 0-.4.4-.7.8-.6 1.6.4 3.2.3 4.7-.3.6-.2 1.1.4.7 1.1-.3.6-.6 1.2-.9 1.9z"
    />
    <path
      fill="#fff"
      d="M28.6 14.2c-4.1 0-7.6 2.4-9.2 6.1-1.4 3.2-1.6 7-.4 10.4.3.8-.4 1.6-1.2 1.5-2.2-.4-4.2-1.4-5.8-2.8-.5-.4-.2-1.3.4-1.4 2.1-.4 3.8-1.8 4.6-3.8.6-1.5.4-3.2-.5-4.6C14.8 16.6 11.6 14 8 13.6c-.6 0-.9-.7-.5-1.1 2.6-2.4 6.2-3.7 9.9-3.7 6.1 0 11.2 3.8 11.2 9.4 0 .6-.7.9-1.2.5-1.2-.9-2.6-1.4-4.1-1.5-.6 0-.8-.7-.4-1.1.8-1.1 2.1-1.9 3.5-1.9z"
    />
    <ellipse cx="31.2" cy="22.6" rx="2.1" ry="2.6" fill="#fff" />
    <circle cx="31.6" cy="22.2" r="0.7" fill="#0f172a" />
  </svg>

  <svg
    v-else-if="name === 'redis'"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    aria-hidden="true"
  >
    <rect width="48" height="48" rx="10" fill="#DC382D" />
    <path fill="#fff" opacity="0.28" d="M8 20 24 12l16 8-16 8z" />
    <path fill="#fff" d="M8 22.5 24 14.5 40 22.5 24 30.5z" />
    <path fill="#F9A5A0" d="M8 22.5 24 30.5V14.5z" />
    <path fill="#fff" opacity="0.9" d="M10 27.2 24 34.2l14-7v3.4L24 37.6 10 30.6z" />
    <path fill="#fff" opacity="0.7" d="M10 32.2 24 39.2l14-7v3.2L24 42.4 10 35.4z" />
  </svg>

  <svg
    v-else-if="name === 'docker'"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    aria-hidden="true"
  >
    <rect width="48" height="48" rx="10" fill="#2496ED" />
    <g fill="#fff">
      <rect x="14" y="22" width="5.2" height="5.2" rx="0.6" />
      <rect x="20.2" y="22" width="5.2" height="5.2" rx="0.6" />
      <rect x="26.4" y="22" width="5.2" height="5.2" rx="0.6" />
      <rect x="20.2" y="16" width="5.2" height="5.2" rx="0.6" />
      <rect x="26.4" y="16" width="5.2" height="5.2" rx="0.6" />
      <rect x="26.4" y="10" width="5.2" height="5.2" rx="0.6" />
      <path d="M12 29.4c.8 3.4 3.8 6.2 10.8 6.2 8.4 0 13.2-3.8 15.2-9.2 1.6.1 4.4-.4 5.6-2.2-1.2-.8-3.2-1.2-4.6-1.2h-26c-.6 2.2-.8 4.4-.6 6.4h-.4z" />
    </g>
  </svg>

  <svg
    v-else-if="name === 'fail2ban'"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    aria-hidden="true"
  >
    <rect width="48" height="48" rx="10" fill="#1a3a28" />
    <path
      fill="#7CB342"
      d="M24 8 12 12.4v10.2c0 8.4 5.2 14.6 12 17.4 6.8-2.8 12-9 12-17.4V12.4z"
    />
    <path fill="#1a3a28" d="M18 20.2h12v14H18z" />
    <rect x="20.2" y="22.2" width="2.2" height="10" rx="0.4" fill="#7CB342" />
    <rect x="25.6" y="22.2" width="2.2" height="10" rx="0.4" fill="#7CB342" />
    <path fill="#7CB342" d="M18 18.4h12v3.2H18z" />
  </svg>

  <svg v-else-if="name === 'php'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#777BB3" />
    <text x="24" y="30" text-anchor="middle" fill="#fff" font-size="13" font-weight="800" font-family="Sora, sans-serif">PHP</text>
  </svg>
  <svg v-else-if="name === 'laravel'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#FF2D20" />
    <path fill="#fff" d="M10 30 24 10l14 20-14 8z" />
  </svg>
  <svg v-else-if="name === 'wordpress'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#21759B" />
    <circle cx="24" cy="24" r="12" fill="none" stroke="#fff" stroke-width="3" />
    <text x="24" y="29" text-anchor="middle" fill="#fff" font-size="16" font-weight="800" font-family="Georgia, serif">W</text>
  </svg>
  <svg v-else-if="name === 'python'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#3776AB" />
    <rect x="12" y="12" width="12" height="24" rx="6" fill="#FFD43B" />
    <rect x="24" y="12" width="12" height="24" rx="6" fill="#fff" />
  </svg>
  <svg v-else-if="name === 'django'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#092E20" />
    <text x="24" y="30" text-anchor="middle" fill="#fff" font-size="16" font-weight="800" font-family="Sora, sans-serif">dj</text>
  </svg>
  <svg v-else-if="name === 'fastapi'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#009688" />
    <text x="24" y="30" text-anchor="middle" fill="#fff" font-size="11" font-weight="800" font-family="Sora, sans-serif">API</text>
  </svg>
  <svg v-else-if="name === 'flask'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#111" />
    <path d="M18 12h12l-2 10H20z" fill="#fff" />
    <ellipse cx="24" cy="32" rx="10" ry="7" fill="#fff" opacity="0.85" />
  </svg>
  <svg v-else-if="name === 'nodejs'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#339933" />
    <text x="24" y="30" text-anchor="middle" fill="#fff" font-size="14" font-weight="800" font-family="Sora, sans-serif">JS</text>
  </svg>
  <svg v-else-if="name === 'nextjs'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#000" />
    <text x="24" y="30" text-anchor="middle" fill="#fff" font-size="14" font-weight="800" font-family="Sora, sans-serif">N</text>
  </svg>
  <svg v-else-if="name === 'express'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#222" />
    <text x="24" y="29" text-anchor="middle" fill="#fff" font-size="18" font-weight="700" font-family="Sora, sans-serif">ex</text>
  </svg>
  <svg v-else-if="name === 'react'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#0a0a0a" />
    <ellipse cx="24" cy="24" rx="14" ry="6" fill="none" stroke="#61DAFB" stroke-width="2" />
    <ellipse cx="24" cy="24" rx="14" ry="6" fill="none" stroke="#61DAFB" stroke-width="2" transform="rotate(60 24 24)" />
    <ellipse cx="24" cy="24" rx="14" ry="6" fill="none" stroke="#61DAFB" stroke-width="2" transform="rotate(120 24 24)" />
    <circle cx="24" cy="24" r="3" fill="#61DAFB" />
  </svg>
  <svg v-else-if="name === 'vue'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#fff" />
    <path fill="#42B883" d="M8 12h10l6 10 6-10h10L24 40z" />
    <path fill="#35495E" d="M16 12h8l0 0 8 0-8 14z" />
  </svg>
  <svg v-else-if="name === 'postgres'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#336791" />
    <ellipse cx="24" cy="22" rx="10" ry="12" fill="#fff" />
    <circle cx="20" cy="20" r="1.4" fill="#336791" />
  </svg>
  <svg v-else-if="name === 'mongodb'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#116149" />
    <path fill="#A6C75B" d="M24 8c4 8 8 12 8 20 0 6-3 10-8 12-5-2-8-6-8-12 0-8 4-12 8-20z" />
  </svg>
  <svg v-else-if="name === 'git'" :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#F05032" />
    <path fill="#fff" d="M24 10 38 24 24 38 10 24z" />
    <circle cx="24" cy="24" r="3" fill="#F05032" />
  </svg>
  <svg v-else :width="size" :height="size" viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="10" fill="#64748b" />
    <circle cx="24" cy="24" r="8" fill="#fff" />
  </svg>
</template>
