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
  lookingAway: boolean // вбок или вверх: второй экран, подсказчик
  lookingDown: boolean // вниз: лист с расчётами, клавиатура — разрешено, только счётчик
  embedding?: number[]
  yaw?: number // рад; для активной проверки «живое лицо» (знак не важен — нужны обе стороны)
  real?: number
  live?: number
}

const PHONE_SCORE = 0.45
// Отпечаток лица берётся только с качественного кадра — иначе тот же человек «не совпадает»:
// * лицо крупное (на снимках ниже ~150 px сходство разных людей завышено, а одного — занижено);
// * детектор уверен в лице;
// * лицо смотрит в камеру: при наклоне к листу или повороте эмбеддинг заметно уплывает.
const EMBED_MIN_FACE_PX = 160
const EMBED_MIN_SCORE = 0.8
const EMBED_MAX_ANGLE = 0.35 // рад ≈ 20°
const YAW_AWAY = 0.6 // рад ≈ 35°
const PITCH_AWAY = 0.5
// Знак наклона в Human: принимаем pitch > 0 за «голова опущена». Проверить на живой камере
// и при необходимости поменять знак здесь.
const PITCH_DOWN_SIGN = 1

export function readFrame(r: Result): Frame {
  const faces = r.face.filter((f) => f.score >= 0.5)
  const main = faces[0]
  const a = main?.rotation?.angle
  const down = !!a && a.pitch * PITCH_DOWN_SIGN > PITCH_AWAY
  const frontal = !!a && Math.abs(a.yaw) < EMBED_MAX_ANGLE && Math.abs(a.pitch) < EMBED_MAX_ANGLE
  const good = faces.length === 1 && main.box[2] >= EMBED_MIN_FACE_PX && (main.faceScore ?? main.score) >= EMBED_MIN_SCORE && frontal
  return {
    faces: faces.length,
    phone: r.object.some((o) => o.label === 'cell phone' && o.score >= PHONE_SCORE),
    lookingAway: !!a && (Math.abs(a.yaw) > YAW_AWAY || (Math.abs(a.pitch) > PITCH_AWAY && !down)),
    lookingDown: down,
    embedding: good && main.embedding?.length ? Array.from(main.embedding) : undefined,
    yaw: faces.length === 1 ? a?.yaw : undefined,
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
