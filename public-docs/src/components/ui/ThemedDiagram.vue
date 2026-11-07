<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useThemeStore } from '@/stores/themeStore'

defineProps<{
  name: string
  alt: string
  caption: string
}>()

const { isDark } = storeToRefs(useThemeStore())
</script>

<template>
  <figure class="not-prose diagram">
    <img :src="`/diagrams/${name}-${isDark ? 'dark' : 'light'}.svg`" :alt="alt" />
    <figcaption>{{ caption }}</figcaption>
  </figure>
</template>

<style scoped>
.diagram {
  margin: 1.75rem 0;
  border: 1px solid var(--border);
  background: var(--surface);
}
.diagram img {
  display: block;
  width: 100%;
  height: auto;
  padding: var(--space-6);
}
.diagram figcaption {
  border-top: 1px solid var(--border);
  padding: var(--space-3) var(--space-5);
  font-size: var(--text-sm);
  color: var(--text-2);
}
</style>
