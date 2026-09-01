<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="flex min-h-[60vh] flex-col items-center justify-center gap-6 px-6 text-center">
    <p class="text-6xl font-bold opacity-20">404</p>
    <h1 class="text-2xl font-semibold">Page not found</h1>
    <p class="max-w-sm text-sm text-[var(--color-text-muted)]">
      This URL doesn't match any docs page. It may have moved or the link may be stale.
    </p>
    <RouterLink
      to="/"
      class="rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
    >
      Back to docs home
    </RouterLink>
  </div>
</template>
