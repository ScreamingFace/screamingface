// Checks the agent skill references against the public names of the release that the docs
// version names.
//
//   node scripts/check-skill-names.mjs [--python <path to a python with screamingface installed>]
//
// Without --python, the script creates a temporary virtual environment and installs
// `screamingface==<docs version>` into it. It fails when
//   - a `sf.<Name>` in the references is not in `screamingface.__all__`, or
//   - a name in `screamingface.__all__` appears in no reference.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { sfClientVersion } from './sf-version.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const REFERENCES = path.join(ROOT, 'agent-skill', 'skills', 'screamingface', 'references')

function pythonWithRelease(version) {
  const given = process.argv.indexOf('--python')
  if (given !== -1) return process.argv[given + 1]
  if (process.env.SF_PYTHON) return process.env.SF_PYTHON
  const venv = fs.mkdtempSync(path.join(os.tmpdir(), 'sf-skill-names-'))
  execFileSync('python3', ['-m', 'venv', venv], { stdio: 'inherit' })
  const python = path.join(venv, 'bin', 'python')
  execFileSync(python, ['-m', 'pip', 'install', '--quiet', `screamingface==${version}`], {
    stdio: 'inherit',
  })
  return python
}

function publicNames(python) {
  // DO_NOT_TRACK keeps the import from writing the analytics preference file.
  const out = execFileSync(
    python,
    ['-c', 'import json, screamingface as sf; print(json.dumps(sf.__all__))'],
    { encoding: 'utf8', env: { ...process.env, DO_NOT_TRACK: '1' } },
  )
  return JSON.parse(out.trim().split('\n').pop())
}

const version = sfClientVersion()
const names = new Set(
  publicNames(pythonWithRelease(version)).filter((name) => !name.startsWith('__')),
)
const text = fs
  .readdirSync(REFERENCES)
  .filter((file) => file.endsWith('.md'))
  .map((file) => fs.readFileSync(path.join(REFERENCES, file), 'utf8'))
  .join('\n')

const referenced = new Set(
  [...text.matchAll(/\bsf\.([A-Za-z_][A-Za-z0-9_]*)/g)]
    .map((m) => m[1])
    .filter((name) => !name.startsWith('__')),
)
const unknown = [...referenced].filter((name) => !names.has(name)).sort()
const unreferenced = [...names].filter((name) => !new RegExp(`\\b${name}\\b`).test(text)).sort()

console.log(
  `release ${version}: ${names.size} public names, ${referenced.size} sf.<Name> tokens in the references`,
)
if (unknown.length) console.error(`not in __all__: ${unknown.join(', ')}`)
if (unreferenced.length) console.error(`in no reference: ${unreferenced.join(', ')}`)
process.exit(unknown.length || unreferenced.length ? 1 : 0)
