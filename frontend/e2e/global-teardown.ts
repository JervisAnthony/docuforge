import { rmSync } from 'node:fs'
import path from 'node:path'

export default function globalTeardown() {
  rmSync(path.resolve(process.cwd(), '.e2e-fixtures'), { recursive: true, force: true })
}
