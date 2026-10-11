// Второй детектор телефона: EfficientDet-Lite0 (MediaPipe, COCO, Apache-2.0). centernet из Human
// не узнаёт телефон крупным планом и задней стороной к камере — а именно так его держат перед лицом.
// Модель и wasm раздаются своим сервером из /models/mediapipe (scripts/copy-proctor-models.mjs).
import type { ObjectDetector } from '@mediapipe/tasks-vision'

const BASE = '/models/mediapipe'

export async function loadPhoneDetector(): Promise<ObjectDetector> {
  const { FilesetResolver, ObjectDetector } = await import('@mediapipe/tasks-vision')
  const fileset = await FilesetResolver.forVisionTasks(`${BASE}/wasm`)
  const options = (delegate: 'GPU' | 'CPU') => ({
    baseOptions: { modelAssetPath: `${BASE}/efficientdet_lite0.tflite`, delegate },
    runningMode: 'IMAGE' as const,
    categoryAllowlist: ['cell phone'],
    scoreThreshold: 0.3,
    maxResults: 3,
  })
  try {
    return await ObjectDetector.createFromOptions(fileset, options('GPU'))
  } catch {
    // нет WebGL2 — тот же детектор на CPU (wasm), медленнее, но в пределах интервала кадров
    return ObjectDetector.createFromOptions(fileset, options('CPU'))
  }
}

/** Наибольшая уверенность «cell phone» в кадре (0 — телефона нет). */
export function phoneScore(d: ObjectDetector, src: HTMLVideoElement | HTMLCanvasElement): number {
  let best = 0
  for (const det of d.detect(src).detections) for (const c of det.categories) best = Math.max(best, c.score)
  return best
}
