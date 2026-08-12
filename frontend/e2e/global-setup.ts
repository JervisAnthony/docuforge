import { rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

export default function globalSetup() {
  const fixtureRoot = path.resolve(process.cwd(), '.e2e-fixtures')
  const generator = path.join(path.dirname(fileURLToPath(import.meta.url)), 'generate_fixtures.py')
  const pythonCommand = process.env.DOCUFORGE_PYTHON?.trim() || 'python'

  rmSync(fixtureRoot, { recursive: true, force: true })
  const result = spawnSync(pythonCommand, [generator, fixtureRoot], {
    cwd: process.cwd(),
    stdio: 'inherit',
  })
  if (result.error) {
    throw result.error
  }
  if (result.status !== 0) {
    throw new Error(`E2E fixture generation failed with status ${result.status ?? 'unknown'}.`)
  }
}
