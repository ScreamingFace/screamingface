import { createSSRApp, type Component } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia } from 'pinia'

// Renders one docs page to an HTML string for the Markdown generator
// (`scripts/build-skill.mjs`). A memory router with a catch-all route makes every
// `RouterLink` resolve, and `router.push(path)` sets the active route that the sidebar reads.
export async function render(component: Component, path: string): Promise<string> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:p(.*)*', component: { render: () => null } }],
  })
  const app = createSSRApp(component)
  app.use(router)
  app.use(createPinia())
  await router.push(path)
  await router.isReady()
  return renderToString(app)
}
