import { execSync } from 'node:child_process'

// The screamingface release the docs are built at: the newest non-rc `screamingface-v*`
// tag reachable from HEAD. The build fails when no tag is reachable (a shallow clone), so
// the footer can never name a version that was not read from a release.
export function sfClientVersion() {
  let tag = ''
  try {
    tag = execSync(
      "git describe --tags --match 'screamingface-v[0-9]*' --exclude '*rc*' --abbrev=0 HEAD",
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] },
    ).trim()
  } catch {
    // handled below
  }
  const version = tag.replace(/^screamingface-v/, '')
  if (!version) {
    throw new Error(
      'Cannot determine the screamingface version: no screamingface-v* git tag is reachable. Fetch the full history with tags (git fetch --unshallow --tags).',
    )
  }
  return version
}
