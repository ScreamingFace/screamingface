<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ChevronDown } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { useThemeStore } from '@/stores/themeStore'

const route = useRoute()
const themeStore = useThemeStore()
const { isDark } = storeToRefs(themeStore)
const { toggleTheme } = themeStore

// Top-level product/section links. Add an entry here for each documentation
// section you introduce (see src/navigation/ for the matching sidebar data).
const products = [
  { name: 'Home', path: '/' },
  { name: 'Get started with SF Client', path: '/sf-client' },
  { name: 'API reference', path: '/sf-client/api/modules' },
  { name: 'Learn more', path: '/learn' },
]

const currentProduct = computed(() => {
  const path = route.path
  if (path.startsWith('/sf-client/api')) return 'API reference'
  if (path.startsWith('/sf-client')) return 'Get started with SF Client'
  if (path.startsWith('/learn')) return 'Learn more'
  return 'Home'
})

const isActive = (productPath: string) => {
  if (productPath === '/') return route.path === '/'
  // Both tabs live under /sf-client/*, so the reference tab owns /sf-client/api/*
  // and the get-started tab owns everything else under /sf-client.
  if (productPath.startsWith('/sf-client/api')) return route.path.startsWith('/sf-client/api')
  if (productPath === '/sf-client')
    return route.path.startsWith('/sf-client') && !route.path.startsWith('/sf-client/api')
  return route.path.startsWith(productPath)
}

// The product link row collapses below md, so the current-product label becomes
// the only way to reach another section, so it has to be a control, not text.
const productsOpen = ref(false)
watch(
  () => route.path,
  () => {
    productsOpen.value = false
  },
)

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') productsOpen.value = false
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <header class="sticky top-0 z-50 border-b border-border bg-background">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <nav class="flex items-center justify-between h-16">
        <!-- Brand: the 😱 mark is the shipped system emoji (never recoloured or redrawn). -->
        <RouterLink to="/" class="flex items-center gap-2.5 group">
          <span
            class="text-[22px] leading-none transition-transform duration-200 group-hover:scale-105"
            aria-hidden="true"
            >😱</span
          >
          <span class="flex items-baseline gap-2">
            <span class="text-[15px] font-medium tracking-tight text-foreground"
              >ScreamingFace</span
            >
            <span class="font-mono text-[10px] tracking-[0.14em] uppercase text-muted-foreground"
              >Docs</span
            >
          </span>
        </RouterLink>

        <!-- Product Navigation: square underline tab, gold when active -->
        <div class="hidden md:flex items-center gap-1 self-stretch">
          <RouterLink
            v-for="product in products"
            :key="product.path"
            :to="product.path"
            :class="[
              'inline-flex items-center px-3 text-sm border-b-2 transition-colors duration-150',
              isActive(product.path)
                ? 'text-primary border-primary font-medium'
                : 'text-muted-foreground border-transparent hover:text-foreground',
            ]"
          >
            {{ product.name }}
          </RouterLink>
        </div>

        <!-- Mobile menu + actions -->
        <div class="flex items-center gap-2">
          <!-- Mobile product switcher -->
          <div class="md:hidden relative">
            <div v-if="productsOpen" class="fixed inset-0 z-40" @click="productsOpen = false" />

            <button
              type="button"
              class="relative z-50 flex items-center gap-1 px-2 py-1.5 text-sm font-normal text-sidebar-primary rounded-md hover:bg-muted/50"
              :aria-expanded="productsOpen"
              aria-haspopup="true"
              @click="productsOpen = !productsOpen"
            >
              {{ currentProduct }}
              <ChevronDown
                class="w-3.5 h-3.5 transition-transform"
                :class="productsOpen && 'rotate-180'"
              />
            </button>

            <div
              v-if="productsOpen"
              class="absolute right-0 z-50 mt-2 w-40 rounded-md border border-border bg-background shadow-lg overflow-hidden"
            >
              <RouterLink
                v-for="product in products"
                :key="product.path"
                :to="product.path"
                :class="[
                  'block px-3 py-2 text-sm',
                  isActive(product.path)
                    ? 'text-sidebar-primary bg-sidebar-primary/10'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
                ]"
              >
                {{ product.name }}
              </RouterLink>
              <a
                href="https://github.com/ScreamingFace"
                target="_blank"
                rel="noopener noreferrer"
                class="sm:hidden block px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 border-t border-border"
              >
                GitHub
              </a>
            </div>
          </div>

          <!-- Theme Toggle -->
          <button
            @click="toggleTheme"
            class="p-2 text-muted-foreground hover:text-foreground transition-colors"
            :aria-label="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
          >
            <!-- Sun icon (shown in dark mode) -->
            <svg
              v-if="isDark"
              class="w-5 h-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
              />
            </svg>
            <!-- Moon icon (shown in light mode) -->
            <svg v-else class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
              />
            </svg>
          </button>

          <!-- Roadmap link -->
          <!-- <RouterLink
            to="/roadmap"
            class="hidden sm:flex items-center gap-2 px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground border border-border hover:border-primary/50 transition-colors duration-200"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
            Roadmap
          </RouterLink> -->

          <!-- GitHub link -->
          <a
            href="https://github.com/ScreamingFace"
            target="_blank"
            rel="noopener noreferrer"
            class="hidden sm:flex items-center gap-2 px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground border border-border hover:border-primary/50 transition-colors duration-200"
          >
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <path
                fill-rule="evenodd"
                d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                clip-rule="evenodd"
              />
            </svg>
            GitHub
          </a>
        </div>
      </nav>
    </div>
  </header>
</template>
