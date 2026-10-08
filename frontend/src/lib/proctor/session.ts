// Сессия цифрового проктора: одна на вкладку, переживает переход со страницы выбора уровня на страницу
// теста. Видео и звук анализируются на устройстве; наружу отдаются только счётчики по заданию,
// эмбеддинг лица (для серверной сверки с эталоном) и — при согласии — один кадр на старте.
import type { Human } from '@vladmandic/human'
import { useSyncExternalStore } from 'react'
import { AudioMonitor } from './audio'
import { detect, EMBEDDING_MODEL, isDark, lightCheck, loadHuman, similarity } from './vision'

export interface ProctorCounters {
  no_face_ms: number
  multi_face_ms: number
  phone_hits: number
  look_away_ms: number
  speech_ms: number
  cam_lost_ms: number
  mic_lost_ms: number
}

export interface ProctorLive {
  active: boolean
  faces: number
  phone: boolean
  lookingAway: boolean
  speaking: boolean
  camOk: boolean
  micOk: boolean
  mismatch: boolean // локальная сверка с эталоном старта (сервер сверяет сам)
  level: number
  noFaceMs: number // сколько подряд нет лица — для предупреждения
}

export interface CheckResult {
  camOk: boolean
  light: boolean
  faces: number
  phone: boolean
  real: number | null
  live: number | null
  embedding: number[] | null
}

const ZERO: ProctorCounters = { no_face_ms: 0, multi_face_ms: 0, phone_hits: 0, look_away_ms: 0, speech_ms: 0, cam_lost_ms: 0, mic_lost_ms: 0 }
const IDLE: ProctorLive = { active: false, faces: 0, phone: false, lookingAway: false, speaking: false, camOk: false, micOk: false, mismatch: false, level: 0, noFaceMs: 0 }

const VISION_MS = 500
const AUDIO_MS = 100
const EMBED_EVERY_MS = 10_000
const SERVER_EVERY_MS = 60_000 // эмбеддинг на сервер — примерно раз в минуту, в случайный момент
const MATCH_MIN = 0.5

class ProctorSession {
  stream: MediaStream | null = null
  model = EMBEDDING_MODEL
  private human: Human | null = null
  private video: HTMLVideoElement | null = null
  private canvas = document.createElement('canvas')
  private audio: AudioMonitor | null = null
  private ref: number[] | null = null
  private counters: ProctorCounters = { ...ZERO }
  private live: ProctorLive = IDLE
  private listeners = new Set<() => void>()
  private audioTimer: number | null = null
  private visionTimer: number | null = null
  private busy = false
  private lastVision = 0
  private lastEmbedAt = 0
  private fresh: { v: number[]; at: number } | null = null
  private nextServerAt = 0
  private phoneRun = 0
  private phoneOff = 0
  private noFace = 0

  /** Доступ к камере и микрофону + загрузка моделей. Вызывать по действию пользователя. */
  async open(): Promise<void> {
    if (!this.stream) {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: { echoCancellation: true, noiseSuppression: true },
      })
      const v = document.createElement('video')
      v.muted = true
      v.playsInline = true
      v.srcObject = this.stream
      await v.play()
      this.video = v
      this.audio = new AudioMonitor(this.stream)
    }
    await this.audio?.resume()
    this.human ??= await loadHuman()
    this.startAudio()
  }

  get opened() {
    return !!this.stream && !!this.human
  }

  /** Проверка перед стартом: несколько кадров с эмбеддингом и признаками живого лица. */
  async check(): Promise<CheckResult> {
    if (!this.human || !this.video) throw new Error('Проктор не запущен')
    const l = lightCheck(this.video, this.canvas)
    const track = this.stream?.getVideoTracks()[0]
    const camOk = !!track && track.readyState === 'live' && !track.muted
    const fr = await detect(this.human, this.video, { embed: true, liveness: true })
    return { camOk, light: !isDark(l), faces: fr.faces, phone: fr.phone, real: fr.real ?? null, live: fr.live ?? null, embedding: fr.embedding ?? null }
  }

  /** Свежий эмбеддинг (для старта следующей попытки без повторной проверки). */
  async capture(): Promise<number[] | null> {
    if (!this.human || !this.video) return null
    const fr = await detect(this.human, this.video, { embed: true })
    return fr.embedding ?? null
  }

  /** Кадр JPEG 320×240 для работодателя (только при согласии). */
  snapshotJpeg(): string | null {
    if (!this.video?.videoWidth) return null
    const c = document.createElement('canvas')
    c.width = 320
    c.height = 240
    c.getContext('2d')?.drawImage(this.video, 0, 0, 320, 240)
    return c.toDataURL('image/jpeg', 0.7)
  }

  micPeak(reset = false): number {
    const p = this.audio?.peak ?? 0
    if (reset && this.audio) this.audio.peak = 0
    return p
  }

  /** Начать наблюдение за попыткой. ref — эмбеддинг со старта (для мгновенной локальной сверки). */
  start(ref: number[] | null, lostBeforeMs = 0) {
    this.ref = ref
    this.counters = { ...ZERO, cam_lost_ms: lostBeforeMs }
    this.fresh = ref ? { v: ref, at: performance.now() } : null
    this.nextServerAt = performance.now() + SERVER_EVERY_MS * (0.5 + Math.random())
    this.lastVision = performance.now()
    this.live = { ...IDLE, active: true, camOk: true, micOk: true, faces: 1 }
    this.emit()
    if (this.visionTimer != null) clearInterval(this.visionTimer)
    this.visionTimer = window.setInterval(() => void this.visionTick(), VISION_MS)
  }

  get active() {
    return this.live.active
  }

  /** Новое задание — новые счётчики. */
  resetItem() {
    this.counters = { ...ZERO }
  }

  counts(): ProctorCounters {
    return { ...this.counters }
  }

  /** Эмбеддинг для серверной сверки, если подошло время (раз в ~минуту) и есть свежий. */
  embeddingForServer(): number[] | undefined {
    const now = performance.now()
    if (now < this.nextServerAt || !this.fresh || now - this.fresh.at > 15_000) return undefined
    this.nextServerAt = now + SERVER_EVERY_MS * (0.5 + Math.random())
    return this.fresh.v
  }

  /** Приостановить наблюдение (экран результата), не закрывая камеру: следующая попытка — без новой проверки. */
  pause() {
    if (this.visionTimer != null) clearInterval(this.visionTimer)
    this.visionTimer = null
    this.live = { ...IDLE }
    this.emit()
  }

  stop() {
    for (const t of [this.audioTimer, this.visionTimer]) if (t != null) clearInterval(t)
    this.audioTimer = this.visionTimer = null
    this.audio?.close()
    this.audio = null
    this.stream?.getTracks().forEach((t) => t.stop())
    this.stream = null
    this.video = null
    this.ref = this.fresh = null
    this.live = IDLE
    this.emit()
  }

  subscribe = (fn: () => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  getLive = () => this.live

  private emit() {
    for (const fn of this.listeners) fn()
  }

  private set(patch: Partial<ProctorLive>) {
    const next = { ...this.live, ...patch }
    if (Object.keys(patch).some((k) => next[k as keyof ProctorLive] !== this.live[k as keyof ProctorLive])) {
      this.live = next
      this.emit()
    }
  }

  private startAudio() {
    if (this.audioTimer != null) return
    this.audioTimer = window.setInterval(() => {
        const a = this.audio?.tick()
        if (!a) return
        if (this.live.active) {
          this.counters.speech_ms += a.speechMs
          this.counters.mic_lost_ms += a.lostMs
        }
        this.set({ speaking: a.speaking, micOk: a.micOk, level: Math.round(a.level * 20) / 20 })
      }, AUDIO_MS)
  }

  private async visionTick() {
    if (this.busy || !this.human || !this.video || !this.live.active) return
    this.busy = true
    try {
      const now = performance.now()
      const dt = Math.min(5000, now - this.lastVision)
      this.lastVision = now
      const track = this.stream?.getVideoTracks()[0]
      const dark = isDark(lightCheck(this.video, this.canvas))
      if (!track || track.readyState === 'ended' || track.muted || !track.enabled || dark) {
        this.counters.cam_lost_ms += dt
        this.set({ camOk: false })
        return
      }
      const embed = now - this.lastEmbedAt >= EMBED_EVERY_MS
      const fr = await detect(this.human, this.video, { embed })
      if (fr.faces === 0) {
        this.counters.no_face_ms += dt
        this.noFace += dt
      } else this.noFace = 0
      if (fr.faces >= 2) this.counters.multi_face_ms += dt
      if (fr.lookingAway) this.counters.look_away_ms += dt
      // телефон: эпизод засчитывается после двух кадров подряд, заканчивается после двух кадров без него
      if (fr.phone) {
        this.phoneRun += 1
        this.phoneOff = 0
        if (this.phoneRun === 2) this.counters.phone_hits += 1
      } else if (++this.phoneOff >= 2) this.phoneRun = 0
      let mismatch = this.live.mismatch
      if (embed) {
        this.lastEmbedAt = now
        if (fr.embedding) {
          this.fresh = { v: fr.embedding, at: now }
          if (this.ref) mismatch = similarity(this.human, this.ref, fr.embedding) < MATCH_MIN
        }
      }
      this.set({ camOk: true, faces: fr.faces, phone: this.phoneRun >= 2, lookingAway: fr.lookingAway, mismatch, noFaceMs: Math.round(this.noFace / 1000) * 1000 })
    } catch {
      // единичная ошибка инференса не должна останавливать наблюдение
    } finally {
      this.busy = false
    }
  }
}

export const proctor = new ProctorSession()

export function useProctorLive(): ProctorLive {
  return useSyncExternalStore(proctor.subscribe, proctor.getLive)
}

/** Предупреждения проктора в реальном времени (кандидат может сразу исправить ситуацию). */
export function proctorWarning(live: ProctorLive): string | null {
  if (!live.active) return null
  if (!live.camOk) return 'Камера выключена или закрыта. Включите её — без камеры отметка «Тест с проктором» будет снята.'
  if (!live.micOk) return 'Микрофон выключен. Включите его — без микрофона отметка «Тест с проктором» будет снята.'
  if (live.phone) return 'В кадре телефон. Уберите его: телефон в кадре на трёх заданиях аннулирует попытку.'
  if (live.faces > 1) return 'В кадре несколько человек. Проходить тест нужно самостоятельно.'
  if (live.mismatch) return 'Лицо в кадре не похоже на лицо со старта теста. Это будет проверено.'
  if (live.noFaceMs >= 5000) return 'Вас не видно в кадре. Отсутствие дольше 20 секунд засчитывается как уход со страницы.'
  if (live.speaking) return 'Слышна речь. Пожалуйста, не зачитывайте задания вслух.'
  return null
}
