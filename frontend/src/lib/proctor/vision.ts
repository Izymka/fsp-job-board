// Зрение цифрового проктора на устройстве кандидата: Human (TF.js) — лица, поворот головы,
// эмбеддинг лица (faceres), живое лицо (liveness/antispoof) и объекты COCO («cell phone»).
// Модели раздаются своим сервером из /models/human (scripts/copy-human-models.mjs).
import type { Config, Human, Result } from '@vladmandic/human'

export const EMBEDDING_MODEL = 'human-3.3-faceres'

const BASE: Partial<Config> = {
  modelBasePath: '/models/human/',
  debug: false,
  cacheSensitivity: 0, // каждый кадр анализируется заново: проктору нужны свежие результаты
  filter: { enabled: false },
  face: {
    enabled: true,
    detector: { enabled: true, rotation: false, maxDetected: 3, minConfidence: 0.5, return: false },
    mesh: { enabled: true },
    iris: { enabled: false },
    emotion: { enabled: false },
    description: { enabled: false },
    antispoof: { enabled: false },
    liveness: { enabled: false },
    attention: { enabled: false },
  },
  body: { enabled: false },
  hand: { enabled: false },
  object: { enabled: true, minConfidence: 0.35, maxDetected: 5 },
  gesture: { enabled: false },
  segmentation: { enabled: false },
} as Partial<Config>

let instance: Promise<Human> | null = null

export function loadHuman(): Promise<Human> {
  instance ??= (async () => {
    const { Human } = await import('@vladmandic/human')
    const h = new Human(BASE)
    await h.load()
    await h.warmup()
    return h
  })()
  instance.catch(() => (instance = null))
  return instance
}

export interface Frame {
  faces: number
  phone: boolean
  lookingAway: boolean
  embedding?: number[]
  real?: number
  live?: number
}

const PHONE_SCORE = 0.45
// эмбеддинг мелкого лица ненадёжен (на снимках ниже ~150 px сходство разных людей завышено):
// отпечаток берётся только с достаточно крупного лица — кандидата просят сесть ближе
const EMBED_MIN_FACE_PX = 160
const YAW_AWAY = 0.6 // рад ≈ 35°
const PITCH_AWAY = 0.5

export function readFrame(r: Result): Frame {
  const faces = r.face.filter((f) => f.score >= 0.5)
  const main = faces[0]
  const a = main?.rotation?.angle
  return {
    faces: faces.length,
    phone: r.object.some((o) => o.label === 'cell phone' && o.score >= PHONE_SCORE),
    lookingAway: !!a && (Math.abs(a.yaw) > YAW_AWAY || Math.abs(a.pitch) > PITCH_AWAY),
    embedding: faces.length === 1 && main.box[2] >= EMBED_MIN_FACE_PX && main.embedding?.length ? Array.from(main.embedding) : undefined,
    real: main?.real,
    live: main?.live,
  }
}

export async function detect(h: Human, video: HTMLVideoElement, opts: { embed?: boolean; liveness?: boolean } = {}): Promise<Frame> {
  const r = await h.detect(video, {
    face: { description: { enabled: !!opts.embed }, antispoof: { enabled: !!opts.liveness }, liveness: { enabled: !!opts.liveness } },
  } as Partial<Config>)
  return readFrame(r)
}

export function similarity(h: Human, a: number[], b: number[]): number {
  return h.match.similarity(a, b)
}

/** Средняя яркость и контраст кадра: камера закрыта шторкой/пальцем или в полной темноте. */
export function lightCheck(video: HTMLVideoElement, canvas: HTMLCanvasElement): { mean: number; std: number } {
  canvas.width = 32
  canvas.height = 24
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx || !video.videoWidth) return { mean: 0, std: 0 }
  ctx.drawImage(video, 0, 0, 32, 24)
  const d = ctx.getImageData(0, 0, 32, 24).data
  let s = 0
  let s2 = 0
  const n = d.length / 4
  for (let i = 0; i < d.length; i += 4) {
    const y = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]
    s += y
    s2 += y * y
  }
  const mean = s / n
  return { mean, std: Math.sqrt(Math.max(0, s2 / n - mean * mean)) }
}

export const isDark = (l: { mean: number; std: number }) => l.mean < 20 || l.std < 6
