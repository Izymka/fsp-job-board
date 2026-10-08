// Модели Human для цифрового проктора раздаются своим сервером (без внешних CDN): копируем нужные
// из node_modules в public/models/human перед dev/build.
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = join(root, 'node_modules/@vladmandic/human/models')
const dst = join(root, 'public/models/human')
const MODELS = ['blazeface', 'facemesh', 'faceres', 'antispoof', 'liveness', 'centernet']

if (!existsSync(src)) {
  console.warn('[proctor] @vladmandic/human не установлен — модели не скопированы')
  process.exit(0)
}
mkdirSync(dst, { recursive: true })
for (const m of MODELS) for (const ext of ['json', 'bin']) copyFileSync(join(src, `${m}.${ext}`), join(dst, `${m}.${ext}`))
console.log(`[proctor] модели Human скопированы в public/models/human (${MODELS.join(', ')})`)
