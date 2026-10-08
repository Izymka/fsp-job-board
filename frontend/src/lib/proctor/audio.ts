// Звук для цифрового проктора: детектор речи (VAD по энергии в речевой полосе) и контроль того,
// что микрофон не выключен. Звук не записывается и не покидает устройство — считаются только длительности.

const SPEECH_LO_HZ = 300
const SPEECH_HI_HZ = 3400
const SPEECH_MARGIN_DB = 15 // выше шумового порога — речь
const SPEECH_MIN_MS = 1500 // короче — кашель, щелчок, слово себе под нос
const SPEECH_GAP_MS = 400 // паузы между словами не разрывают фразу
const SILENCE_RMS = 1e-5 // «цифровая тишина» — микрофон заглушён в системе или аппаратно
const SILENCE_LOST_MS = 10_000

export interface AudioTick {
  speaking: boolean
  micOk: boolean
  level: number // 0..1 для индикатора
}

export class AudioMonitor {
  private ctx: AudioContext
  private analyser: AnalyserNode
  private track: MediaStreamTrack
  private freq: Float32Array<ArrayBuffer>
  private time: Float32Array<ArrayBuffer>
  private floor = -70
  private run = 0 // длительность текущей фразы, мс
  private gap = 0
  private silent = 0
  private last = performance.now()
  peak = 0 // максимальный уровень с последнего сброса (проверка «скажите раз-два»)

  constructor(stream: MediaStream) {
    this.track = stream.getAudioTracks()[0]
    this.ctx = new AudioContext()
    const src = this.ctx.createMediaStreamSource(stream)
    this.analyser = this.ctx.createAnalyser()
    this.analyser.fftSize = 2048
    this.analyser.smoothingTimeConstant = 0.3
    src.connect(this.analyser)
    this.freq = new Float32Array(this.analyser.frequencyBinCount)
    this.time = new Float32Array(this.analyser.fftSize)
  }

  async resume() {
    if (this.ctx.state === 'suspended') await this.ctx.resume()
  }

  /** Один шаг анализа; возвращает состояние и сколько мс речи / потери микрофона добавить. */
  tick(): AudioTick & { speechMs: number; lostMs: number } {
    const now = performance.now()
    const dt = Math.min(1000, now - this.last)
    this.last = now
    const t = this.track
    if (!t || t.readyState === 'ended' || t.muted || !t.enabled || this.ctx.state !== 'running') {
      this.run = 0
      return { speaking: false, micOk: false, level: 0, speechMs: 0, lostMs: dt }
    }
    this.analyser.getFloatTimeDomainData(this.time)
    let rms = 0
    for (const x of this.time) rms += x * x
    rms = Math.sqrt(rms / this.time.length)
    this.silent = rms < SILENCE_RMS ? this.silent + dt : 0
    if (this.silent >= SILENCE_LOST_MS) return { speaking: false, micOk: false, level: 0, speechMs: 0, lostMs: dt }

    this.analyser.getFloatFrequencyData(this.freq)
    const hz = this.ctx.sampleRate / this.analyser.fftSize
    let p = 0
    for (let i = Math.floor(SPEECH_LO_HZ / hz); i <= Math.ceil(SPEECH_HI_HZ / hz) && i < this.freq.length; i++) p += 10 ** (this.freq[i] / 10)
    const db = 10 * Math.log10(p + 1e-12)
    // адаптивный шумовой порог: сразу опускается к тишине, поднимается медленно (~минута),
    // поэтому длинная речь не «съедает» порог, а постоянный шум вентилятора — съедает
    this.floor = db < this.floor ? db : this.floor + (db - this.floor) * 0.002
    const level = Math.max(0, Math.min(1, (db - this.floor) / 30))
    this.peak = Math.max(this.peak, level)
    const voiced = db > this.floor + SPEECH_MARGIN_DB
    const before = this.run
    if (voiced) {
      this.run += dt + this.gap
      this.gap = 0
    } else if (this.run > 0) {
      this.gap += dt
      if (this.gap > SPEECH_GAP_MS) this.run = this.gap = 0
    }
    const speaking = this.run >= SPEECH_MIN_MS
    // при пересечении порога засчитывается и начало фразы
    const speechMs = speaking ? (before < SPEECH_MIN_MS ? this.run : this.run - before) : 0
    return { speaking, micOk: true, level, speechMs, lostMs: 0 }
  }

  close() {
    void this.ctx.close()
  }
}
