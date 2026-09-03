// Minimal Jupyter nbformat v4 model + pure helpers for rendering a notebook.
// Kept dependency-free and reactivity-free (pure functions): notebooks are
// imported statically as `?raw` text, so there is nothing reactive to wrap in a
// composable. The parse belongs here in `lib/`, alongside `cn`.

export interface NbOutput {
  output_type: 'execute_result' | 'display_data' | 'stream' | 'error'
  data?: Record<string, string | string[]>
  text?: string | string[]
  name?: string
  ename?: string
  evalue?: string
  traceback?: string[]
  execution_count?: number | null
}

export interface NbCell {
  cell_type: 'markdown' | 'code' | 'raw'
  source: string | string[]
  outputs?: NbOutput[]
  execution_count?: number | null
}

export interface Notebook {
  cells: NbCell[]
  metadata?: {
    kernelspec?: { language?: string; display_name?: string }
    language_info?: { name?: string }
  }
  nbformat?: number
}

// A notebook output flattened into exactly one renderable shape.
export type NormalizedOutput =
  | { kind: 'text'; text: string; stream?: string }
  | { kind: 'error'; text: string }
  | { kind: 'image'; mime: string; data: string }
  | { kind: 'html'; html: string }

// `.ipynb` source and text fields are stored as string | string[] (one entry
// per line). Collapse either form to a single string.
export function joinSource(s: string | string[] | undefined): string {
  return Array.isArray(s) ? s.join('') : (s ?? '')
}

// Parse raw `.ipynb` JSON into a Notebook, degrading to an empty notebook (not a
// throw) so a malformed file renders as nothing rather than crashing the page.
export function parseNotebook(raw: string): Notebook {
  try {
    const nb = JSON.parse(raw) as Notebook
    if (!nb || !Array.isArray(nb.cells)) throw new Error('notebook has no cells[]')
    return nb
  } catch (err) {
    console.error('Failed to parse notebook:', err)
    return { cells: [] }
  }
}

export function notebookLanguage(nb: Notebook): string {
  return nb.metadata?.kernelspec?.language || nb.metadata?.language_info?.name || 'python'
}

// Maps a notebook basename (as written in inter-notebook markdown links, e.g.
// `[02_models](02_models.ipynb)`) to the docs route that renders it. Notebooks
// not listed here have no page yet, so their links are rendered as plain text
// rather than a dead `*.ipynb` href. Extend as more notebooks get wired in.
export const NOTEBOOK_ROUTES: Record<string, string> = {
  '00_overview': '/sf-client',
  '00_quickstart': '/sf-client/reproduce-draco',
}

// Remove a single leading `# Heading` line from a markdown source. Used to drop
// the notebook's own H1 on the first cell, since the docs page header already
// renders the title, while keeping the rest of that cell (lead, callouts, list).
export function stripLeadingHeading(src: string): string {
  return src.replace(/^\s*#\s+[^\n]*\n+/, '')
}

// Pick the richest renderable representation of a single output. Order matters:
// images and rich HTML (widgets, object reprs) win over the text/plain fallback.
export function normalizeOutput(out: NbOutput): NormalizedOutput {
  if (out.output_type === 'stream') {
    return { kind: 'text', text: joinSource(out.text), stream: out.name }
  }
  if (out.output_type === 'error') {
    const text =
      out.traceback && out.traceback.length
        ? out.traceback.join('\n')
        : `${out.ename ?? 'Error'}: ${out.evalue ?? ''}`
    return { kind: 'error', text }
  }
  const data = out.data ?? {}
  if (data['image/png'])
    return { kind: 'image', mime: 'image/png', data: joinSource(data['image/png']) }
  if (data['image/jpeg'])
    return { kind: 'image', mime: 'image/jpeg', data: joinSource(data['image/jpeg']) }
  if (data['text/html']) return { kind: 'html', html: joinSource(data['text/html']) }
  if (data['text/plain']) return { kind: 'text', text: joinSource(data['text/plain']) }
  return { kind: 'text', text: '' }
}
