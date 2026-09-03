<script setup lang="ts">
import { RouterLink } from 'vue-router'

// Entry points into the docs. Only real routes are linked; stubs are marked
// honestly rather than dressed up.
const docs = [
  {
    title: 'Overview',
    to: '/sf-client',
    kicker: 'start here',
    desc: 'What ScreamingFace is, the smallest end-to-end example, and how the Client, engine, and url4 fit together.',
  },
  {
    title: 'Quickstart',
    to: '/sf-client/first-fusion',
    kicker: 'tutorial',
    desc: 'Compose a fusion, run it against a benchmark, and read how it compares to its best single member.',
  },
  {
    title: 'Installation',
    to: '/sf-client/installation',
    kicker: 'setup',
    desc: 'Install the ScreamingFace Client and point it at an engine.',
    draft: true,
  },
  {
    title: 'Learn more',
    to: '/learn',
    kicker: 'concepts',
    desc: 'Architecture, the url4 protocol and SDK, the engine and its trust boundary, caching, and the leaderboard.',
  },
]

const GITHUB = 'https://github.com/ScreamingFace'
</script>

<template>
  <div class="home">
    <!-- ============ HERO ============ -->
    <section class="hero band">
      <p class="kicker">ScreamingFace · documentation</p>
      <h1 class="hero__title">
        Compose model fusions.<br />
        <span class="hero__title-2">Reproduce every run from one line.</span>
      </h1>
      <p class="lead">
        ScreamingFace is an open toolkit for composing model <em>fusions</em>: several models
        answering together, graded against a real benchmark. Every run reproduces from a single
        line, on your own keys.
      </p>

      <div class="actions">
        <RouterLink class="btn btn--primary" to="/sf-client/first-fusion">Quickstart</RouterLink>
        <RouterLink class="btn btn--sec" to="/sf-client">Overview</RouterLink>
        <RouterLink class="btn btn--sec" to="/sf-client/installation">Installation</RouterLink>
        <a class="btn btn--sec" :href="GITHUB" target="_blank" rel="noopener noreferrer">GitHub</a>
      </div>

      <div class="term" role="img" aria-label="Install the Client with pip install screamingface">
        <div class="term__bar">
          <span class="term__dot"></span><span class="term__dot"></span
          ><span class="term__dot"></span>
          <span class="term__name">shell</span>
        </div>
        <pre class="term__body"><span class="term__prompt">$</span> pip install screamingface</pre>
      </div>
    </section>

    <!-- ============ IN THESE DOCS ============ -->
    <section class="docs band">
      <p class="kicker">In these docs</p>
      <div class="grid">
        <RouterLink v-for="d in docs" :key="d.to" class="card" :to="d.to">
          <span class="card__kicker">{{ d.kicker }}</span>
          <span class="card__head">
            <span class="card__title">{{ d.title }}</span>
            <span v-if="d.draft" class="tag">draft</span>
          </span>
          <span class="card__desc">{{ d.desc }}</span>
          <span class="card__go" aria-hidden="true">→</span>
        </RouterLink>
      </div>
    </section>

    <!-- ============ VOCABULARY ============ -->
    <section class="vocab band">
      <p class="kicker">A few terms</p>
      <dl class="defs">
        <div class="def">
          <dt><code>fusion</code></dt>
          <dd>
            A composed AI system built from many models: the artifact you build, run, and share.
          </dd>
        </div>
        <div class="def">
          <dt>
            <RouterLink to="/learn/url4"><code>url4</code></RouterLink>
          </dt>
          <dd>
            A grammar and protocol: one line that describes a fusion and its benchmark run, and
            reproduces it. It is also an address the engine resolves, so anyone holding the
            <code>url4</code> can rerun the result or call the fusion like a single model.
          </dd>
        </div>
        <div class="def">
          <dt>
            <RouterLink to="/learn/engine"><code>engine</code></RouterLink>
          </dt>
          <dd>
            The runtime that executes a fusion. You point the Client at one you run locally, or a
            hosted one.
          </dd>
        </div>
      </dl>
    </section>

    <!-- ============ FOOTER ============ -->
    <footer class="foot band">
      <div class="foot__brand">
        <span class="foot__mark" aria-hidden="true">😱</span>
        <span>
          <span class="foot__name">ScreamingFace</span>
        </span>
      </div>
      <nav class="foot__links">
        <RouterLink to="/sf-client">Overview</RouterLink>
        <RouterLink to="/sf-client/first-fusion">Quickstart</RouterLink>
        <a :href="GITHUB" target="_blank" rel="noopener noreferrer">GitHub</a>
      </nav>
    </footer>
  </div>
</template>

<style scoped>
/* SFDS v2 marketing register. Colour is rationed to the accent (gold); structure
   reads from hairline seams and square edges. Two families: Plex Sans (body) +
   Plex Mono (labels, code); Parastoo carries the one hero line. */
.home {
  color: var(--text);
  font-family: var(--f-sans);
}
.band {
  max-width: 1140px;
  margin: 0 auto;
  padding-left: var(--space-7);
  padding-right: var(--space-7);
}
.kicker {
  font-family: var(--f-mono);
  font-size: var(--text-label);
  font-weight: var(--weight-medium);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--accent-text-low);
  margin: 0 0 var(--space-6);
}
code {
  font-family: var(--f-mono);
  font-size: 0.9em;
  color: var(--text);
}
em {
  font-style: normal;
  color: var(--text);
  font-weight: var(--weight-medium);
}

/* ---------- HERO ---------- */
.hero {
  padding-top: var(--space-12);
  padding-bottom: var(--space-11);
}
.hero__title {
  font-family: var(--f-display);
  font-weight: var(--weight-display);
  font-size: var(--text-hero);
  line-height: var(--leading-hero);
  letter-spacing: var(--tracking-tight);
  margin: 0 0 var(--space-6);
}
.hero__title-2 {
  color: var(--text-2);
}
.lead {
  font-size: var(--text-lead);
  line-height: var(--leading-snug);
  color: var(--text-2);
  max-width: 62ch;
  margin: 0 0 var(--space-8);
}

/* ---------- BUTTONS ---------- */
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-bottom: var(--space-9);
}
.btn {
  display: inline-flex;
  align-items: center;
  font-family: var(--f-sans);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  padding: 10px 18px;
  border: 1px solid transparent;
  border-radius: var(--radius-none);
  text-decoration: none;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease;
}
.btn--primary {
  background: var(--accent-solid);
  color: var(--accent-contrast-text);
}
.btn--primary:hover {
  background: var(--accent-solid-hover);
}
.btn--sec {
  border-color: var(--border);
  color: var(--text);
}
.btn--sec:hover {
  border-color: var(--accent-border-strong);
  color: var(--accent-text-low);
}

/* ---------- INSTALL TERMINAL ---------- */
.term {
  max-width: 460px;
  background: var(--code-bg);
  border: 1px solid var(--code-border);
  border-radius: var(--radius-window);
  overflow: hidden;
}
.term__bar {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--code-border);
}
.term__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #44484d;
}
.term__name {
  margin-left: 6px;
  font-family: var(--f-mono);
  font-size: var(--text-micro);
  color: #8b9096;
}
.term__body {
  margin: 0;
  padding: 16px 18px;
  font-family: var(--f-mono);
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--code-fg);
  overflow-x: auto;
}
.term__prompt {
  color: var(--brand-solid);
  user-select: none;
  margin-right: 10px;
}

/* ---------- IN THESE DOCS ---------- */
.docs {
  padding-top: var(--space-10);
  padding-bottom: var(--space-10);
  border-top: 1px solid var(--border);
}
.grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
}
.card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--bg);
  padding: var(--space-6) var(--space-6) var(--space-7);
  text-decoration: none;
  color: inherit;
  transition: background-color 0.15s ease;
}
.card:hover {
  background: var(--surface);
}
.card__kicker {
  font-family: var(--f-mono);
  font-size: var(--text-label);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--text-2);
}
.card__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.card__title {
  font-size: var(--text-title);
  font-weight: var(--weight-semibold);
  letter-spacing: var(--tracking-tight);
  color: var(--text);
}
.tag {
  font-family: var(--f-mono);
  font-size: var(--text-label);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-2);
  border: 1px solid var(--border);
  padding: 1px 6px;
}
.card__desc {
  font-size: var(--text-sm);
  line-height: var(--leading-snug);
  color: var(--text-2);
  max-width: 42ch;
}
.card__go {
  margin-top: var(--space-2);
  font-family: var(--f-mono);
  color: var(--accent-text-low);
  transition: transform 0.15s ease;
}
.card:hover .card__go {
  transform: translateX(4px);
}

/* ---------- VOCABULARY ---------- */
.vocab {
  padding-top: var(--space-10);
  padding-bottom: var(--space-10);
  border-top: 1px solid var(--border);
}
.defs {
  margin: 0;
  display: grid;
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
}
.def {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: var(--space-6);
  background: var(--bg);
  padding: var(--space-5) var(--space-6);
}
.def dt {
  margin: 0;
}
.def dd {
  margin: 0;
  font-size: var(--text-body);
  line-height: var(--leading-body);
  color: var(--text-2);
  max-width: 60ch;
}

/* ---------- FOOTER ---------- */
.foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
  padding-top: var(--space-9);
  padding-bottom: var(--space-10);
  border-top: 1px solid var(--border);
}
.foot__brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.foot__mark {
  font-size: 22px;
  line-height: 1;
}
.foot__name {
  display: block;
  font-weight: var(--weight-medium);
  color: var(--text);
}
.foot__note {
  display: block;
  font-size: var(--text-sm);
  color: var(--text-2);
}
.foot__links {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6);
}
.foot__links a {
  font-size: var(--text-sm);
  color: var(--text-2);
  text-decoration: none;
}
.foot__links a:hover {
  color: var(--accent-text-low);
}

/* ---------- RESPONSIVE ---------- */
@media (max-width: 760px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .def {
    grid-template-columns: 1fr;
    gap: var(--space-2);
  }
  .hero {
    padding-top: var(--space-10);
  }
}
</style>
