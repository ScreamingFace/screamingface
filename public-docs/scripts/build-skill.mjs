// Generates the Markdown view of the docs from the pages themselves.
//
//   node scripts/build-skill.mjs --dist   writes dist/<route>.md, dist/llms.txt, dist/llms-full.txt
//   node scripts/build-skill.mjs          writes agent-skill/skills/screamingface/references/*.md
//
// Every route is rendered with Vite SSR and `@vue/server-renderer` (scripts/ssr-entry.ts), the
// page header and the `.prose-content` body are converted with turndown, and the build fails
// when a page does not render or leaves HTML or escaped code behind.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import TurndownService from 'turndown'
import { gfm } from 'turndown-plugin-gfm'

import { sfClientVersion } from './sf-version.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SITE = 'https://docs.screamingface.ai'
const SKILL_DIR = path.join(ROOT, 'agent-skill', 'skills', 'screamingface')
const BODY_START = '<div class="prose max-w-none prose-content"'
const SHELL_START =
  /^(\$ |[A-Z_]+=|pip |uv |npm |npx |screamingface |export |claude |curl |just |git |sf\.configure\(\) )/

// ---------------------------------------------------------------- HTML extraction

/** The element that starts at `start`, with its closing tag, by balanced `<tag` counting. */
function balancedElement(html, start, tag) {
  const token = new RegExp(`<${tag}\\b|</${tag}>`, 'g')
  token.lastIndex = start
  let depth = 0
  let m
  while ((m = token.exec(html))) {
    depth += m[0].startsWith('</') ? -1 : 1
    if (depth === 0) return html.slice(start, token.lastIndex)
  }
  throw new Error(`unbalanced <${tag}> at ${start}`)
}

function textOf(html) {
  return html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim()
}

/** The page header (title, description) and the page body of a rendered docs page. */
function extractPage(html, route) {
  const clean = html.replace(/<!--[\s\S]*?-->/g, '')
  const bodyAt = clean.indexOf(BODY_START)
  if (bodyAt === -1) {
    // A page outside DocLayout (the home page): its root element is the body, its first
    // <h1> the title.
    const rootAt = clean.indexOf('<div')
    if (rootAt === -1) throw new Error(`${route}: the rendered page has no root element`)
    const root = balancedElement(clean, rootAt, 'div')
    const h1 = root.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)
    return {
      title: h1 ? textOf(h1[1]).replace(/\s+/g, ' ') : '',
      description: '',
      body: h1 ? root.replace(h1[0], '') : root,
    }
  }
  const body = balancedElement(clean, bodyAt, 'div')
  const headerAt = clean.lastIndexOf('<header', bodyAt)
  let title = ''
  let description = ''
  if (headerAt !== -1) {
    const header = clean.slice(headerAt, clean.indexOf('</header>', headerAt) + 9)
    const h1 = header.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)
    const p = header.match(/<p[^>]*>([\s\S]*?)<\/p>/)
    title = h1 ? textOf(h1[1]) : ''
    description = p ? textOf(p[1]) : ''
  }
  return { title, description, body }
}

// ---------------------------------------------------------------- Markdown conversion

function slug(route) {
  return route.replace(/^\//, '').replace(/\//g, '-') || 'index'
}

function language(node) {
  for (let a = node.parentNode, depth = 0; a && depth < 5; a = a.parentNode, depth++) {
    const cls = (a.getAttribute && a.getAttribute('class')) || ''
    if (cls.includes('nbc__src')) {
      return SHELL_START.test(node.textContent.trimStart()) ? 'bash' : 'python'
    }
    if (cls.includes('rounded-xl')) {
      const label = a.querySelector('span.ml-3')
      const lang = label ? label.textContent.trim() : ''
      return lang === 'text' ? '' : lang
    }
  }
  return ''
}

function makeConverter(linkTarget) {
  const td = new TurndownService({
    headingStyle: 'atx',
    codeBlockStyle: 'fenced',
    bulletListMarker: '-',
    emDelimiter: '*',
  })
  td.use(gfm)
  td.remove(['button', 'style', 'script'])
  // A diagram is replaced by its alt text.
  td.addRule('diagram', {
    filter: ['svg', 'img'],
    replacement: (_content, node) => {
      const label = node.getAttribute('aria-label') || node.getAttribute('alt') || ''
      return label ? `\n\n[Diagram: ${label}]\n\n` : ''
    },
  })
  // The language label in the header bar of a code block: it moves into the fence.
  td.addRule('codeLabel', {
    filter: (node) =>
      node.nodeName === 'SPAN' &&
      /\bml-3\b/.test(node.getAttribute('class') || '') &&
      /\btext-zinc-400\b/.test(node.getAttribute('class') || ''),
    replacement: () => '',
  })
  // The decorative title bar of the home page terminal.
  td.addRule('termName', {
    filter: (node) =>
      node.nodeName === 'SPAN' && /\bterm__name\b/.test(node.getAttribute('class') || ''),
    replacement: () => '',
  })
  // The `[n]:` input and output labels of a notebook cell.
  td.addRule('cellCount', {
    filter: (node) =>
      node.nodeName === 'SPAN' && /\bnbc__count\b/.test(node.getAttribute('class') || ''),
    replacement: () => '',
  })
  // Code comes from any <pre>, as plain text, with its language in the fence.
  td.addRule('pre', {
    filter: 'pre',
    replacement: (_content, node) => {
      const text = node.textContent.replace(/\n+$/, '')
      return `\n\n\`\`\`${language(node)}\n${text}\n\`\`\`\n\n`
    },
  })
  // Each tab panel is labelled with the text of its tab.
  td.addRule('tabpanel', {
    filter: (node) => node.getAttribute && node.getAttribute('role') === 'tabpanel',
    replacement: (content, node) => {
      const root = node.parentNode
      const tabs = Array.from(root.querySelectorAll('[role="tab"]'))
      const panels = Array.from(root.childNodes).filter(
        (n) => n.getAttribute && n.getAttribute('role') === 'tabpanel',
      )
      const label = tabs[panels.indexOf(node)]
      return `\n\n**${label ? label.textContent.trim() : 'Tab'}**\n\n${content.trim()}\n\n`
    },
  })
  td.addRule('tablist', {
    filter: (node) => node.getAttribute && node.getAttribute('role') === 'tablist',
    replacement: () => '',
  })
  // An internal link points at the Markdown of the target page.
  td.addRule('link', {
    filter: (node) => node.nodeName === 'A' && node.getAttribute('href'),
    replacement: (content, node) => {
      const href = node.getAttribute('href')
      const parts = Array.from(node.childNodes).filter((n) => n.nodeType === 1)
      const text =
        parts.length > 1
          ? parts
              .map((n) => n.textContent.trim())
              .filter((t) => t && t !== '→')
              .join(' ')
          : content.trim() || href
      const m = href.match(/^(\/[^#?]*)(#.*)?$/)
      if (m) {
        const route = m[1].replace(/\/$/, '') || '/'
        const target = linkTarget(route)
        const sep = node.previousSibling && node.previousSibling.nodeName === 'A' ? ' ' : ''
        return `${sep}[${text}](${target ? target + (m[2] ?? '') : SITE + href})`
      }
      return `[${text}](${href})`
    },
  })
  return td
}

// ---------------------------------------------------------------- Rendering

async function renderPages(vite) {
  const { routes } = await vite.ssrLoadModule('/src/router/routes.ts')
  const { render } = await vite.ssrLoadModule('/scripts/ssr-entry.ts')
  const pages = []
  for (const route of routes) {
    if (route.path.includes(':')) continue
    const component = (await route.component()).default
    const html = await render(component, route.path)
    pages.push({ route: route.path, ...extractPage(html, route.path) })
  }
  return pages
}

/** Pages in sidebar order, grouped by the top-level entries of the navigation trees. */
async function navGroups(vite, pages) {
  const sf = await vite.ssrLoadModule('/src/navigation/sf-client.ts')
  const learn = await vite.ssrLoadModule('/src/navigation/learn.ts')
  const byRoute = new Map(pages.map((p) => [p.route, p]))
  const seen = new Set()
  const groups = []
  const links = (entries) =>
    entries.flatMap((e) =>
      'path' in e ? [e, ...(e.children ? links(e.children) : [])] : links(e.children),
    )
  for (const tree of [
    sf.sfClientNavigation,
    sf.sfClientReferenceNavigation,
    learn.learnNavigation,
  ]) {
    let loose = null
    for (const entry of tree) {
      const entries = 'path' in entry ? [entry] : links(entry.children)
      const group =
        'path' in entry
          ? (loose ??= { title: 'Overview', routes: [] })
          : { title: entry.title, routes: [] }
      for (const l of entries) {
        if (byRoute.has(l.path) && !seen.has(l.path)) {
          seen.add(l.path)
          group.routes.push(l.path)
        }
      }
      if (!('path' in entry)) groups.push(group)
      else if (!groups.includes(group)) groups.push(group)
    }
  }
  const rest = pages.filter((p) => !seen.has(p.route)).map((p) => p.route)
  if (rest.length) groups.push({ title: 'Other pages', routes: rest })
  return groups.filter((g) => g.routes.length)
}

// ---------------------------------------------------------------- Output

function pageMarkdown(page, converter) {
  const title = page.title || page.route
  const lines = [`# ${title}`, '', `Source: ${SITE}${page.route === '/' ? '' : page.route}`]
  if (page.description) lines.push('', page.description)
  const body = converter.turndown(page.body).trim()
  return `${lines.join('\n')}\n\n${body}\n`
}

function problems(md, route) {
  const found = []
  const outsideFences = md.replace(/```[\s\S]*?```/g, '')
  if (md.length < 300) found.push('body shorter than 300 characters')
  if (/<(div|span|svg|table|tr|td|p|a|ul|li|pre|code|h[1-6])[\s>]/.test(outsideFences))
    found.push('HTML left outside code fences')
  for (const fence of md.match(/```[\s\S]*?```/g) ?? []) {
    if (/\\[=[\]>_*]/.test(fence)) found.push('escaped characters inside a code fence')
  }
  return found.map((f) => `${route}: ${f}`)
}

function write(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, content)
}

function llmsTxt(groups, byRoute, version) {
  const out = [
    '# ScreamingFace documentation',
    '',
    '> Documentation for the ScreamingFace Client, the Python library `screamingface`. Each link is the Markdown version of one docs page.',
    '',
    `Docs version: ${version}`,
  ]
  for (const g of groups) {
    out.push('', `## ${g.title}`, '')
    for (const route of g.routes) {
      const p = byRoute.get(route)
      const desc = p.description ? `: ${p.description}` : ''
      out.push(`- [${p.title || route}](${SITE}${route === '/' ? '/index' : route}.md)${desc}`)
    }
  }
  return `${out.join('\n')}\n`
}

async function main() {
  const dist = process.argv.includes('--dist')
  const version = sfClientVersion()
  const vite = await createServer({
    configFile: false,
    root: ROOT,
    appType: 'custom',
    logLevel: 'error',
    server: { middlewareMode: true, hmr: false, watch: null },
    plugins: [vue()],
    resolve: { alias: { '@': path.join(ROOT, 'src') } },
    define: { __SF_CLIENT_VERSION__: JSON.stringify(version) },
  })
  try {
    const pages = await renderPages(vite)
    const byRoute = new Map(pages.map((p) => [p.route, p]))
    const groups = await navGroups(vite, pages)
    const ordered = groups.flatMap((g) => g.routes)
    const known = new Set(pages.map((p) => p.route))
    const mode = dist ? 'endpoint' : 'skill'
    const converter = makeConverter((route) => {
      if (!known.has(route)) return null
      return mode === 'endpoint' ? `${route === '/' ? '/index' : route}.md` : `${slug(route)}.md`
    })
    const markdown = new Map()
    const failures = []
    for (const route of ordered) {
      const md = pageMarkdown(byRoute.get(route), converter)
      failures.push(...problems(md, route))
      markdown.set(route, md)
    }
    if (failures.length) {
      console.error(failures.join('\n'))
      throw new Error(`${failures.length} page(s) did not convert cleanly`)
    }
    if (dist) {
      const out = path.join(ROOT, 'dist')
      if (!fs.existsSync(out)) throw new Error('dist/ does not exist: run `vite build` first')
      for (const [route, md] of markdown)
        write(path.join(out, `${route === '/' ? 'index' : route.slice(1)}.md`), md)
      write(path.join(out, 'llms.txt'), llmsTxt(groups, byRoute, version))
      write(path.join(out, 'llms-full.txt'), `${[...markdown.values()].join('\n---\n\n')}`)
      console.log(`dist: ${markdown.size} pages, llms.txt, llms-full.txt (docs version ${version})`)
    } else {
      const refs = path.join(SKILL_DIR, 'references')
      fs.rmSync(refs, { recursive: true, force: true })
      for (const [route, md] of markdown) write(path.join(refs, `${slug(route)}.md`), md)
      console.log(`references: ${markdown.size} pages (docs version ${version})`)
    }
  } finally {
    await vite.close()
  }
}

main().catch((error) => {
  console.error(error.message)
  process.exit(1)
})
