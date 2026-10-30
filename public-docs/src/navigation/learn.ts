import type { NavEntry } from '@/composables/useDocNavigation'

// "Learn" section sidebar — the Divio "Explanation" quadrant (the "why" and the
// background, read away from the code). Uses the shared NavEntry model: a group
// labels its children and is never clickable; a link points at a page.
// Architecture is a plain top-level link, so it sits above the labelled group.
export const learnNavigation: NavEntry[] = [
  { title: 'Architecture', path: '/learn' },
  {
    title: 'Explanation',
    children: [
      { title: 'url4', path: '/learn/url4' },
      { title: 'url4 SDK', path: '/learn/url4-sdk' },
      { title: 'Files in url4', path: '/learn/url4-files' },
      { title: 'ScreamingFace Engine', path: '/learn/engine' },
      { title: 'Caching and compute', path: '/learn/caching' },
      { title: 'AI gateway', path: '/learn/ai-gateway' },
      { title: 'Leaderboard', path: '/learn/leaderboard' },
    ],
  },
]
