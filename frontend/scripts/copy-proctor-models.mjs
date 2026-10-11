// Модели цифрового проктора раздаются своим сервером (без внешних CDN): копируем нужные
// из node_modules в public/models перед dev/build.
// * Human — public/models/human;
// * wasm MediaPipe — public/models/mediapipe/wasm. Сама модель EfficientDet-Lite0 (float16) в npm-пакет
//   не входит и лежит в репозитории: public/models/mediapipe/efficientdet_lite0.tflite.
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

const human = join(root, 'node_modules/@vladmandic/human/models')
const MODELS = ['blazeface', 'facemesh', 'faceres', 'antispoof', 'liveness', 'centernet']
if (existsSync(human)) {
  const dst = join(root, 'public/models/human')
  mkdirSync(dst, { recursive: true })
  for (const m of MODELS) for (const ext of ['json', 'bin']) copyFileSync(join(human, `${m}.${ext}`), join(dst, `${m}.${ext}`))
  console.log(`[proctor] модели Human скопированы в public/models/human (${MODELS.join(', ')})`)
} else console.warn('[proctor] @vladmandic/human не установлен — модели не скопированы')

// FilesetResolver выбирает сборку с SIMD или без неё по возможностям браузера
const mediapipe = join(root, 'node_modules/@mediapipe/tasks-vision/wasm')
const WASM = ['vision_wasm_internal', 'vision_wasm_nosimd_internal']
if (existsSync(mediapipe)) {
  const dst = join(root, 'public/models/mediapipe/wasm')
  mkdirSync(dst, { recursive: true })
  for (const m of WASM) for (const ext of ['js', 'wasm']) copyFileSync(join(mediapipe, `${m}.${ext}`), join(dst, `${m}.${ext}`))
  console.log('[proctor] wasm MediaPipe скопирован в public/models/mediapipe/wasm')
} else console.warn('[proctor] @mediapipe/tasks-vision не установлен — wasm не скопирован')
