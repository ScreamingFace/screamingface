<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Menu, X } from 'lucide-vue-next'
import { useCodeLangStore } from '@/stores/codelangStore'
import { useDocNavigation, type NavEntry } from '@/composables/useDocNavigation'
import NavTree from './NavTree.vue'

interface Props {
  // Optional: when omitted, the page header is skipped entirely (e.g. a notebook
  // page whose NotebookViewer renders the notebook's own title as content).
  title?: string
  description?: string
  navigation: NavEntry[]
  // Which version of the documented thing these pages describe. Optional because
  // DocLayout also serves sections that have no version to claim.
  version?: { prefix: string; label: string; url: string }
}

const props = defineProps<Props>()
const route = useRoute()
const { reset: resetCodeLang } = useCodeLangStore()

// Below lg the sidebar is off-canvas. Above it this stays false and is inert,
// because the drawer classes are all lg:-overridden.
const navOpen = ref(false)

watch(
  () => route.path,
  () => {
    resetCodeLang()
    navOpen.value = false
  },
)

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') navOpen.value = false
}

// Keep the sidebar scroll position across navigations. Each page renders its own
// DocLayout, so the scroll container remounts on every route change and would
// otherwise jump back to the top. Persist it per section (keyed by the first nav
// entry's title, which is distinct per tab) so the get-started, reference and
// Learn sidebars keep independent positions.
const sidebarScroll = ref<HTMLElement | null>(null)
const scrollKey = `docSidebarScroll:${props.navigation[0]?.title ?? 'root'}`
const saveSidebarScroll = () => {
  if (sidebarScroll.value) sessionStorage.setItem(scrollKey, String(sidebarScroll.value.scrollTop))
}

// Deep-linkable headings: give every section heading in the prose a stable slug
// id (from its text, kept if the author already set one), and append a hover "#"
// anchor so a reader can grab the link. Scrolling uses scrollIntoView because the
// doc content lives in a nested overflow container, not the window.
const content = ref<HTMLElement | null>(null)

const slugify = (text: string) =>
  text
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')

const enhanceHeadings = () => {
  const root = content.value
  if (!root) return
  const used = new Set<string>()
  root.querySelectorAll<HTMLElement>('h2, h3, h4').forEach((h) => {
    if (h.closest('.not-prose')) return
    if (!h.id) {
      const base = slugify(h.textContent ?? '') || 'section'
      let id = base
      let n = 2
      while (used.has(id) || document.getElementById(id)) id = `${base}-${n++}`
      h.id = id
    }
    used.add(h.id)
    if (!h.querySelector('.heading-anchor')) {
      const a = document.createElement('a')
      a.className = 'heading-anchor'
      a.href = `#${h.id}`
      a.textContent = '#'
      a.setAttribute('aria-label', 'Link to this section')
      h.appendChild(a)
    }
  })
}

const scrollToHash = () => {
  const id = route.hash ? decodeURIComponent(route.hash.slice(1)) : ''
  if (!id) return
  document.getElementById(id)?.scrollIntoView()
}

onMounted(async () => {
  document.addEventListener('keydown', onKeydown)
  await nextTick()
  const saved = sessionStorage.getItem(scrollKey)
  if (saved !== null && sidebarScroll.value) sidebarScroll.value.scrollTop = Number(saved)
  enhanceHeadings()
  scrollToHash()
})

// A hash-only navigation (e.g. a cross-page link to #section) does not remount the
// layout, so re-run the scroll when the hash changes.
watch(
  () => route.hash,
  () => scrollToHash(),
)
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  saveSidebarScroll()
})

// Active state and the sidebar tree belong to NavTree; this layout only needs
// the prev/next pair.
const { prevPage, nextPage } = useDocNavigation(() => props.navigation)
</script>

<template>
  <div class="flex min-h-[calc(100vh-4rem)]">
    <!-- Backdrop, drawer only -->
    <div
      v-if="navOpen"
      class="lg:hidden fixed inset-0 z-30 bg-background/80 backdrop-blur-sm"
      @click="navOpen = false"
    />

    <!-- Sidebar: one element, two layouts. Off-canvas below lg, a static
         column above it, so the drawer reuses NavTree rather than copying it. -->
    <aside
      :class="[
        'w-64 flex flex-col border-r border-border/50 bg-sidebar',
        'fixed inset-y-0 left-0 z-40 pt-16 transition-transform duration-200',
        'lg:sticky lg:inset-y-auto lg:top-16 lg:z-auto lg:h-[calc(100vh-4rem)] lg:pt-0 lg:translate-x-0',
        navOpen ? 'translate-x-0' : '-translate-x-full',
      ]"
    >
      <button
        type="button"
        class="lg:hidden self-end m-3 p-1 text-muted-foreground hover:text-foreground"
        aria-label="Close navigation"
        @click="navOpen = false"
      >
        <X class="w-5 h-5" />
      </button>

      <div ref="sidebarScroll" class="flex-1 overflow-y-auto py-6 px-4" @scroll="saveSidebarScroll">
        <nav>
          <NavTree :entries="navigation" />
        </nav>
      </div>

      <!-- Version footer: the nav above is flex-1, so this sits on the bottom edge. -->
      <div v-if="version" class="border-t border-border/50 px-4 py-3">
        <p class="text-xs text-muted-foreground">
          {{ version.prefix }}
          <!-- Underlined at rest: the sidebar sits outside .prose-content, so it
               inherits none of the layout's link styling. -->
          <a
            :href="version.url"
            target="_blank"
            rel="noopener"
            class="font-mono text-primary underline underline-offset-2 hover:text-accent"
            >{{ version.label }}</a
          >
        </p>
      </div>
    </aside>

    <!-- Main content -->
    <div class="flex-1 overflow-y-auto">
      <div class="max-w-4xl mx-auto px-6 py-10">
        <button
          type="button"
          class="lg:hidden mb-8 flex items-center gap-2 px-3 py-2 text-sm rounded-md border border-border/50 text-muted-foreground hover:text-foreground hover:border-primary/40"
          @click="navOpen = true"
        >
          <Menu class="w-4 h-4" />
          Menu
        </button>

        <!-- Page header (skipped when no title/description, e.g. notebook pages) -->
        <header v-if="title || description" class="mb-12 pb-8 border-b border-border">
          <h1
            v-if="title"
            class="text-4xl sm:text-5xl font-semibold tracking-tight text-foreground mb-4"
          >
            {{ title }}
          </h1>
          <p
            v-if="description"
            class="text-lg sm:text-xl text-muted-foreground leading-relaxed max-w-3xl"
          >
            {{ description }}
          </p>
        </header>

        <!-- Content slot -->
        <div ref="content" class="prose max-w-none prose-content">
          <slot />
        </div>

        <!-- Prev / Next navigation -->
        <div
          v-if="prevPage || nextPage"
          class="flex justify-between items-center mt-16 pt-8 border-t border-border gap-4"
        >
          <RouterLink
            v-if="prevPage"
            :to="prevPage.path"
            class="flex items-center gap-2 px-4 py-3 border border-border bg-card hover:border-primary/50 transition-colors group max-w-[45%]"
          >
            <span class="text-muted-foreground group-hover:text-primary transition-colors">←</span>
            <div class="text-right min-w-0">
              <div class="text-xs text-muted-foreground mb-0.5">Previous</div>
              <div
                class="text-sm font-medium text-foreground group-hover:text-primary transition-colors truncate"
              >
                {{ prevPage.title }}
              </div>
            </div>
          </RouterLink>
          <div v-else />

          <RouterLink
            v-if="nextPage"
            :to="nextPage.path"
            class="flex items-center gap-2 px-4 py-3 border border-border bg-card hover:border-primary/50 transition-colors group max-w-[45%] ml-auto"
          >
            <div class="text-left min-w-0">
              <div class="text-xs text-muted-foreground mb-0.5">Next</div>
              <div
                class="text-sm font-medium text-foreground group-hover:text-primary transition-colors truncate"
              >
                {{ nextPage.title }}
              </div>
            </div>
            <span class="text-muted-foreground group-hover:text-primary transition-colors">→</span>
          </RouterLink>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.prose-content {
  color: var(--color-foreground);
}

.prose-content :deep(h2:not(.not-prose h2)) {
  font-family: var(--font-sans);
  font-size: 1.625rem;
  font-weight: var(--weight-semibold);
  margin-top: 3rem;
  margin-bottom: 1.25rem;
  padding-bottom: 0.625rem;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-foreground);
  letter-spacing: -0.025em;
}

.prose-content :deep(h3:not(.not-prose h3)) {
  font-family: var(--font-sans);
  font-size: 1.375rem;
  font-weight: var(--weight-semibold);
  margin-top: 2.25rem;
  margin-bottom: 0.875rem;
  color: var(--color-foreground);
  letter-spacing: -0.02em;
}

.prose-content :deep(h4:not(.not-prose h4)) {
  font-family: var(--font-sans);
  font-size: 1.125rem;
  font-weight: var(--weight-medium);
  margin-top: 1.75rem;
  margin-bottom: 0.625rem;
  color: var(--color-foreground);
  letter-spacing: -0.015em;
}

.prose-content :deep(p:not(.not-prose p)) {
  color: var(--color-muted-foreground);
  line-height: 1.75;
  margin-bottom: 1rem;
}

.prose-content :deep(ul:not(.not-prose ul)) {
  list-style-type: disc;
  padding-left: 1.5rem;
  margin-bottom: 1rem;
}

.prose-content :deep(ol:not(.not-prose ol)) {
  list-style-type: decimal;
  padding-left: 1.5rem;
  margin-bottom: 1rem;
}

.prose-content :deep(li:not(.not-prose li)) {
  color: var(--color-muted-foreground);
  margin-bottom: 0.5rem;
  line-height: 1.6;
}

.prose-content :deep(li:not(.not-prose li) strong) {
  color: var(--color-foreground);
}

.prose-content :deep(code) {
  padding: 0.125rem 0.375rem;
  border-radius: 0;
  background-color: var(--color-muted);
  color: var(--color-foreground);
  font-size: 0.875rem;
  font-family: var(--font-mono);
}

.prose-content :deep(pre:not(.not-prose pre)) {
  padding: 1rem;
  border-radius: var(--radius-window);
  background-color: var(--code-bg);
  border: 1px solid var(--code-border);
  overflow-x: auto;
  margin-bottom: 1.5rem;
  font-family: var(--font-mono);
  font-size: 0.875rem;
  line-height: 1.6;
}

.prose-content :deep(.not-prose pre) {
  padding: 0;
  border-radius: 0;
  background-color: transparent;
  border: none;
  margin-bottom: 0;
}

.prose-content :deep(pre:not(.not-prose pre) code) {
  background-color: transparent;
  padding: 0;
  color: var(--code-fg);
  font-family: var(--font-mono);
}

.prose-content :deep(.not-prose pre code) {
  background-color: transparent;
  padding: 0;
}

.prose-content :deep(blockquote:not(.not-prose blockquote)) {
  border-left: 2px solid var(--color-primary);
  padding-left: 1rem;
  font-style: normal;
  color: var(--color-muted-foreground);
  margin: 1.5rem 0;
}

.prose-content :deep(table:not(.not-prose table)) {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 1.5rem;
}

.prose-content :deep(th:not(.not-prose th)) {
  font-family: var(--font-sans);
  text-align: left;
  padding: 0.75rem;
  background-color: var(--color-muted);
  font-weight: var(--weight-semibold);
  border-bottom: 1px solid var(--color-border);
  color: var(--color-foreground);
}

.prose-content :deep(td:not(.not-prose td)) {
  padding: 0.75rem;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-muted-foreground);
}

.prose-content :deep(a:not(.not-prose a)) {
  color: var(--accent-text-low);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.prose-content :deep(a:not(.not-prose a):hover) {
  color: var(--accent-text-high);
}

/* Reset prose link styles inside .not-prose, but preserve explicit text-color classes */
.prose-content :deep(.not-prose a:not([class*='text-'])) {
  color: inherit;
  text-decoration: none;
}

.prose-content :deep(strong:not(.not-prose strong)) {
  font-family: var(--font-sans);
  color: var(--color-foreground);
  font-weight: 500;
}

/* Deep-linkable headings: offset the scroll target below the sticky navbar, and
   reveal a "#" anchor on hover for grabbing the section link. */
.prose-content :deep(h2),
.prose-content :deep(h3),
.prose-content :deep(h4) {
  scroll-margin-top: 5rem;
}

.prose-content :deep(a.heading-anchor) {
  margin-left: 0.4em;
  color: var(--color-muted-foreground);
  text-decoration: none;
  font-weight: 400;
  opacity: 0;
  transition: opacity 0.12s ease-in-out;
}

.prose-content :deep(h2:hover a.heading-anchor),
.prose-content :deep(h3:hover a.heading-anchor),
.prose-content :deep(h4:hover a.heading-anchor),
.prose-content :deep(a.heading-anchor:focus) {
  opacity: 0.55;
}

.prose-content :deep(a.heading-anchor:hover) {
  opacity: 0.95;
  color: var(--accent-text-low);
  text-decoration: none;
}
</style>
