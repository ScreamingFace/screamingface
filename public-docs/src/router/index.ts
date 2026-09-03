import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/pages/HomePage.vue'),
    },
    {
      path: '/sf-client',
      name: 'sf-client',
      component: () => import('@/pages/sf-client/Index.vue'),
    },
    {
      path: '/sf-client/installation',
      name: 'sf-client-installation',
      component: () => import('@/pages/sf-client/InstallationPage.vue'),
    },
    {
      path: '/sf-client/first-fusion',
      name: 'sf-client-first-fusion',
      component: () => import('@/pages/sf-client/FirstFusionPage.vue'),
    },
    {
      path: '/sf-client/reproduce-draco',
      name: 'sf-client-reproduce-draco',
      component: () => import('@/pages/sf-client/QuickstartPage.vue'),
    },
    {
      path: '/sf-client/guides/clients',
      name: 'sf-client-guides-clients',
      component: () => import('@/pages/sf-client/guides/ClientsPage.vue'),
    },
    {
      path: '/sf-client/guides/connections',
      name: 'sf-client-guides-connections',
      component: () => import('@/pages/sf-client/guides/ConnectionsPage.vue'),
    },
    {
      path: '/sf-client/guides/models',
      name: 'sf-client-guides-models',
      component: () => import('@/pages/sf-client/guides/ModelsPage.vue'),
    },
    {
      path: '/sf-client/guides/fusions',
      name: 'sf-client-guides-fusions',
      component: () => import('@/pages/sf-client/guides/FusionsPage.vue'),
    },
    {
      path: '/sf-client/guides/pipelines',
      name: 'sf-client-guides-pipelines',
      component: () => import('@/pages/sf-client/guides/PipelinesPage.vue'),
    },
    {
      path: '/sf-client/guides/benchmarks',
      name: 'sf-client-guides-benchmarks',
      component: () => import('@/pages/sf-client/guides/BenchmarksPage.vue'),
    },
    {
      path: '/sf-client/guides/running-an-evaluation',
      name: 'sf-client-guides-evaluation',
      component: () => import('@/pages/sf-client/guides/EvaluationPage.vue'),
    },
    {
      path: '/sf-client/guides/leaderboards',
      name: 'sf-client-guides-leaderboards',
      component: () => import('@/pages/sf-client/guides/LeaderboardsPage.vue'),
    },
    {
      path: '/sf-client/guides/reproduce-and-share',
      name: 'sf-client-guides-url4',
      component: () => import('@/pages/sf-client/guides/Url4Page.vue'),
    },
    {
      path: '/sf-client/api/recipes',
      name: 'sf-client-api-recipes',
      component: () => import('@/pages/sf-client/api/RecipesPage.vue'),
    },
    {
      path: '/sf-client/api/models',
      name: 'sf-client-api-models',
      component: () => import('@/pages/sf-client/api/ModelsCatalogPage.vue'),
    },
    {
      path: '/sf-client/api/benchmarks',
      name: 'sf-client-api-benchmarks',
      component: () => import('@/pages/sf-client/api/BenchmarksPage.vue'),
    },
    {
      path: '/sf-client/api/reports',
      name: 'sf-client-api-reports',
      component: () => import('@/pages/sf-client/api/ReportsPage.vue'),
    },
    {
      path: '/sf-client/api/candidate-result',
      name: 'sf-client-api-candidate-result',
      component: () => import('@/pages/sf-client/api/CandidateResultPage.vue'),
    },
    {
      path: '/sf-client/api/usage',
      name: 'sf-client-api-usage',
      component: () => import('@/pages/sf-client/api/UsagePage.vue'),
    },
    {
      path: '/sf-client/api/clients',
      name: 'sf-client-api-clients',
      component: () => import('@/pages/sf-client/api/ClientsPage.vue'),
    },
    {
      path: '/sf-client/api/fusions',
      name: 'sf-client-api-fusions',
      component: () => import('@/pages/sf-client/api/FusionsPage.vue'),
    },
    {
      path: '/sf-client/api/pipelines',
      name: 'sf-client-api-pipelines',
      component: () => import('@/pages/sf-client/api/PipelinesPage.vue'),
    },
    {
      path: '/sf-client/api/url4',
      name: 'sf-client-api-url4',
      component: () => import('@/pages/sf-client/api/Url4Page.vue'),
    },
    {
      path: '/sf-client/api/connections',
      name: 'sf-client-api-connections',
      component: () => import('@/pages/sf-client/api/ConnectionsPage.vue'),
    },
    {
      path: '/sf-client/api/modules',
      name: 'sf-client-api-modules',
      component: () => import('@/pages/sf-client/api/ModulesPage.vue'),
    },
    {
      path: '/sf-client/api/errors',
      name: 'sf-client-api-errors',
      component: () => import('@/pages/sf-client/api/ErrorsPage.vue'),
    },
    {
      path: '/sf-client/api/events',
      name: 'sf-client-api-events',
      component: () => import('@/pages/sf-client/api/EventsPage.vue'),
    },
    {
      path: '/sf-client/api/leaderboards',
      name: 'sf-client-api-leaderboards',
      component: () => import('@/pages/sf-client/api/LeaderboardsPage.vue'),
    },
    {
      path: '/learn',
      name: 'learn',
      component: () => import('@/pages/learn/ArchitecturePage.vue'),
    },
    {
      path: '/learn/url4',
      name: 'learn-url4',
      component: () => import('@/pages/learn/Url4Page.vue'),
    },
    {
      path: '/learn/engine',
      name: 'learn-engine',
      component: () => import('@/pages/learn/EnginePage.vue'),
    },
    {
      path: '/learn/url4-sdk',
      name: 'learn-url4-sdk',
      component: () => import('@/pages/learn/Url4SdkPage.vue'),
    },
    {
      path: '/learn/caching',
      name: 'learn-caching',
      component: () => import('@/pages/learn/CachingPage.vue'),
    },
    {
      path: '/learn/ai-gateway',
      name: 'learn-ai-gateway',
      component: () => import('@/pages/learn/GatewayPage.vue'),
    },
    {
      path: '/learn/leaderboard',
      name: 'learn-leaderboard',
      component: () => import('@/pages/learn/LeaderboardPage.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/pages/NotFoundPage.vue'),
    },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

export default router
