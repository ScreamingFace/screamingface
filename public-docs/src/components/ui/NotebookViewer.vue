<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import MarkdownIt from 'markdown-it'
import { useHighlight } from '@/composables/useHighlight'
import { trackCodeCopy } from '@/lib/analytics'
import {
  type Notebook,
  type NbCell,
  type NormalizedOutput,
  NOTEBOOK_ROUTES,
  joinSource,
  normalizeOutput,
  notebookLanguage,
  stripLeadingHeading,
} from '@/lib/notebook'

const props = withDefaults(
  defineProps<{
    notebook: Notebook
    // Initial collapse state for code cells.
    defaultCollapsed?: boolean
    // Show the notebook's own leading H1. Toggle off to hide it (e.g. when the
    // docs page header already renders the title).
    showTitle?: boolean
    // basename -> route for inter-notebook links; unknowns render as plain text.
    linkMap?: Record<string, string>
  }>(),
  { defaultCollapsed: false, showTitle: true, linkMap: () => NOTEBOOK_ROUTES },
)

const router = useRouter()
const { highlight } = useHighlight()

// Trusted, first-party notebooks: `html: true` lets the markdown cells use the
// occasional inline HTML entity. `text/html` outputs (widgets, object reprs) are
// rendered separately via v-html below.
const md = new MarkdownIt({ html: true, linkify: true })

// Rewrite the hand-authored relative `*.ipynb` / `*.md` links: point the ones we
// have a page for at their route, and render the rest as plain text (strip the
// anchor) so nothing 404s. Non-notebook links (http, anchors) pass through.
let stripDepth = 0
const defaultLinkOpen =
  md.renderer.rules.link_open ??
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const hrefIdx = token?.attrIndex('href') ?? -1
  const attr = hrefIdx >= 0 ? token?.attrs?.[hrefIdx] : undefined
  // WHY the typeof guard: markdown-it 15 ships its own typings (14 had none, so
  // @types/markdown-it supplied them) and widens a token attribute to
  // `[name: string, value: string | number]`, and attrSet/attrJoin genuinely accept numbers.
  // An href is a string in every path we produce, but a numeric value cannot be a notebook
  // link, so narrowing to string and otherwise not matching is the honest read rather than
  // a cast that asserts something the type no longer guarantees.
  const href = attr?.[1]
  const match = typeof href === 'string' ? href.match(/([^/]+)\.(ipynb|md)$/i) : null
  const basename = match?.[1]
  if (attr && basename) {
    const route = props.linkMap[basename]
    if (route) {
      attr[1] = route
    } else {
      stripDepth++
      return '' // no page yet, drop the anchor, keep the label text
    }
  }
  return defaultLinkOpen(tokens, idx, options, env, self)
}
const defaultLinkClose =
  md.renderer.rules.link_close ??
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_close = (tokens, idx, options, env, self) => {
  if (stripDepth > 0) {
    stripDepth--
    return ''
  }
  return defaultLinkClose(tokens, idx, options, env, self)
}

const lang = computed(() => notebookLanguage(props.notebook))

interface RenderCell {
  id: number
  type: NbCell['cell_type']
  html?: string
  code?: string
  codeHtml?: string
  execCount?: number | null
  outputs?: NormalizedOutput[]
}

// Index of the first markdown cell, so `stripTitle` only touches the real title.
const firstMarkdownId = computed(() =>
  props.notebook.cells.findIndex((c) => c.cell_type === 'markdown'),
)

const cells = computed<RenderCell[]>(() =>
  props.notebook.cells.map((cell, id): RenderCell => {
    if (cell.cell_type === 'markdown') {
      let src = joinSource(cell.source)
      if (!props.showTitle && id === firstMarkdownId.value) {
        src = stripLeadingHeading(src)
      }
      return { id, type: 'markdown', html: md.render(src) }
    }
    if (cell.cell_type === 'code') {
      const code = joinSource(cell.source)
      return {
        id,
        type: 'code',
        code,
        codeHtml: highlight(code, lang.value),
        execCount: cell.execution_count ?? null,
        // Drop empty stream/text outputs so blank lines don't render a cell.
        outputs: (cell.outputs ?? [])
          .map(normalizeOutput)
          .filter((o) => !(o.kind === 'text' && !o.text.trim())),
      }
    }
    return { id, type: 'raw', code: joinSource(cell.source) }
  }),
)

const collapsed = ref<Record<number, boolean>>({})
const isCollapsed = (id: number) => collapsed.value[id] ?? props.defaultCollapsed
const toggle = (id: number) => {
  collapsed.value[id] = !isCollapsed(id)
}

// Per-cell copy feedback (a shared useCopy ref would flash every button at once).
const copiedId = ref<number | null>(null)
let copyTimer: ReturnType<typeof setTimeout> | undefined
async function copyCell(id: number, code: string) {
  try {
    await navigator.clipboard?.writeText(code)
    trackCodeCopy()
    copiedId.value = id
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => (copiedId.value = null), 1500)
  } catch {
    /* clipboard unavailable, ignore */
  }
}

const prompt = (n?: number | null) => (n == null ? ' ' : n)

// Rewritten inter-notebook links are plain <a href="/route"> inside v-html, so
// intercept clicks on them for SPA navigation instead of a full page reload.
function onClick(e: MouseEvent) {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
    return
  }
  const anchor = (e.target as HTMLElement | null)?.closest('a')
  const href = anchor?.getAttribute('href')
  if (href && href.startsWith('/')) {
    e.preventDefault()
    router.push(href)
  }
}
</script>

<template>
  <div class="nb" @click="onClick">
    <template v-for="cell in cells" :key="cell.id">
      <!-- Markdown cell: rendered inside the page's prose context -->
      <div v-if="cell.type === 'markdown'" v-html="cell.html" />

      <!-- Code cell -->
      <div v-else-if="cell.type === 'code'" class="nb-code not-prose">
        <div class="nb-bar">
          <button
            class="nb-toggle"
            :aria-expanded="!isCollapsed(cell.id)"
            :title="isCollapsed(cell.id) ? 'Expand' : 'Collapse'"
            @click="toggle(cell.id)"
          >
            <span class="nb-chevron" :class="{ collapsed: isCollapsed(cell.id) }">▾</span>
            <span class="nb-count">In [{{ prompt(cell.execCount) }}]</span>
          </button>
          <button class="nb-copy" @click="copyCell(cell.id, cell.code ?? '')">
            {{ copiedId === cell.id ? 'Copied' : 'Copy' }}
          </button>
        </div>

        <pre v-show="!isCollapsed(cell.id)" class="nb-src"><code v-html="cell.codeHtml" /></pre>

        <div v-if="cell.outputs?.length" v-show="!isCollapsed(cell.id)" class="nb-out">
          <div v-for="(o, i) in cell.outputs" :key="i" class="nb-out-item">
            <pre v-if="o.kind === 'text'" class="nb-out-text">{{ o.text }}</pre>
            <pre v-else-if="o.kind === 'error'" class="nb-out-error">{{ o.text }}</pre>
            <img
              v-else-if="o.kind === 'image'"
              :src="`data:${o.mime};base64,${o.data}`"
              class="nb-out-img"
              alt="Notebook output"
            />
            <!-- Trusted first-party notebook: widget / repr HTML rendered as-is -->
            <div v-else-if="o.kind === 'html'" class="nb-out-html" v-html="o.html" />
          </div>
        </div>
      </div>

      <!-- Raw cell -->
      <pre v-else class="nb-raw not-prose">{{ cell.code }}</pre>
    </template>
  </div>
</template>

<style scoped>
.nb {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

/* --- Code cell: dark surface so the Prism theme (tuned for dark) stays legible,
   consistent with CodeBlock; chrome uses fixed dark tones like CodeBlock. --- */
.nb-code {
  margin: 0.75rem 0;
  border-radius: 0.75rem;
  overflow: hidden;
  background: #18181b;
  box-shadow: var(--shadow-sm);
}

.nb-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.75rem;
  background: #0f0f11;
  border-bottom: 1px solid #27272a;
}

.nb-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: none;
  border: none;
  cursor: pointer;
  color: #a1a1aa;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.75rem;
  padding: 0;
}

.nb-chevron {
  display: inline-block;
  transition: transform 0.15s ease;
}
.nb-chevron.collapsed {
  transform: rotate(-90deg);
}

.nb-count {
  color: #71717a;
}

.nb-copy {
  background: none;
  border: none;
  cursor: pointer;
  color: #a1a1aa;
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: 0.35rem;
  transition:
    color 0.15s ease,
    background 0.15s ease;
}
.nb-copy:hover {
  color: #e4e4e7;
  background: #27272a;
}

.nb-src {
  margin: 0;
  padding: 0.9rem 1rem;
  overflow-x: auto;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.8125rem;
  line-height: 1.6;
  color: #e4e4e7;
  white-space: pre;
}
.nb-src code {
  font-family: inherit;
  background: none;
  padding: 0;
}

/* --- Outputs: theme-aware (adapt to light/dark via tokens) --- */
.nb-out {
  border-top: 1px solid #27272a;
  background: var(--card);
}
.nb-out-item {
  padding: 0.5rem 1rem;
}
.nb-out-text {
  margin: 0;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.8125rem;
  line-height: 1.55;
  white-space: pre-wrap;
  color: var(--muted-foreground);
}
.nb-out-error {
  margin: 0;
  padding: 0.6rem 0.8rem;
  border-radius: 0.5rem;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.8125rem;
  white-space: pre-wrap;
  color: var(--destructive);
  background: color-mix(in oklch, var(--destructive) 10%, transparent);
}
.nb-out-img {
  max-width: 100%;
  border-radius: 0.35rem;
}
/* Rich widget / repr HTML ships its OWN inline light styling (fixed brand ink on
   a white surface, see the SDK's html.py / wv.py) and does NOT adapt to dark
   mode. So this frame is deliberately theme-INDEPENDENT: a themed token would
   flip dark in dark mode and hide the widget's fixed-dark text. The fixed light
   surface below matches the content it wraps, framing it as an embedded preview. */
.nb {
  /* Intentionally NOT flipping theme tokens: the widget content is fixed-light. */
  --nb-preview-surface: #ffffff;
  --nb-preview-ink: #16181d; /* brand ink: matches the widget's own palette */
}
.nb-out-html {
  overflow-x: auto;
  background: var(--nb-preview-surface);
  /* Base color so widget text that INHERITS its color (rather than setting its
     own) is dark on the white card, otherwise it inherits the page's light
     dark-mode foreground and becomes white-on-white. */
  color: var(--nb-preview-ink);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 0.75rem;
  color-scheme: light;
}

.nb-raw {
  margin: 0.75rem 0;
  padding: 0.9rem 1rem;
  border-radius: 0.5rem;
  background: var(--muted);
  color: var(--foreground);
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.8125rem;
  white-space: pre-wrap;
  overflow-x: auto;
}
</style>
