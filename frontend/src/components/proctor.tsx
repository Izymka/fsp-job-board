// Цифровой проктор: проверка перед стартом (с собственным видео), индикаторы во время теста, водяной знак.
import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Camera, CheckCircle2, Circle, Loader2, Mic, MicOff, PenLine, ShieldCheck, Smartphone, UserX, Users, VideoOff } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import { useAuth, useMe } from '../lib/auth'
import { proctor, useProctorLive, type CheckResult } from '../lib/proctor/session'
import type { Me } from '../lib/types'
import { ErrorBox, Modal, Notice } from './ui'

export interface ProctorStart {
  proctored: true
  embeddings: number[][] // несколько качественных кадров проверки: эталон и сверка надёжнее
  embedding_model: string
  snapshot?: string
}

function Check({ ok, pending, children, hint }: { ok: boolean; pending?: boolean; children: ReactNode; hint?: ReactNode }) {
  return (
    <li className="flex items-start gap-2.5 text-sm">
      {pending ? <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted" /> : ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok-600" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-steel" />}
      <span>
        <span className={ok ? 'text-ink' : 'text-ink-soft'}>{children}</span>
        {hint && !ok && <span className="block text-xs text-muted">{hint}</span>}
      </span>
    </li>
  )
}

/** Живое видео из сессии проктора. */
function SelfView({ className }: { className?: string }) {
  const ref = useRef<HTMLVideoElement>(null)
  const live = useProctorLive()
  useEffect(() => {
    const v = ref.current
    if (v && proctor.stream && v.srcObject !== proctor.stream) {
      v.srcObject = proctor.stream
      void v.play().catch(() => undefined)
    }
  }, [live.active, live.camOk])
  return <video ref={ref} muted playsInline autoPlay className={clsx('-scale-x-100 bg-ink object-cover', className)} aria-label="Ваше видео с камеры" />
}

/**
 * Проверка перед тестом с проктором: согласия → доступ к камере и микрофону → чек-лист → эмбеддинги
 * (и кадр, если дано согласие). Видео и звук не покидают устройство.
 */
export function ProctorCheckModal({ open, onClose, onReady }: { open: boolean; onClose: () => void; onReady: (s: ProctorStart) => void }) {
  const { config } = useAuth()
  const meQ = useMe()
  const qc = useQueryClient()
  const me = meQ.data
  const [bio, setBio] = useState(false)
  const [photo, setPhoto] = useState(false)
  const [stage, setStage] = useState<'consent' | 'loading' | 'check'>('consent')
  const [error, setError] = useState<unknown>(null)
  const [res, setRes] = useState<CheckResult | null>(null)
  const [heard, setHeard] = useState(false)
  const live = useProctorLive()

  useEffect(() => {
    if (open && me) {
      setBio(!!me.consents.proctoring_biometric)
      setPhoto(!!me.consents.proctoring_photo)
    }
    if (!open) {
      setStage('consent')
      setRes(null)
      setHeard(false)
      setError(null)
    }
  }, [open, me])

  // проверка повторяется, пока окно открыто: кандидат поправляет свет и положение
  useEffect(() => {
    if (stage !== 'check') return
    let stop = false
    const run = async () => {
      while (!stop) {
        try {
          const r = await proctor.check()
          if (!stop) setRes(r)
          if (proctor.micPeak() > 0.5) setHeard(true)
        } catch (e) {
          if (!stop) setError(e)
        }
        await new Promise((r) => setTimeout(r, 700))
      }
    }
    void run()
    return () => {
      stop = true
    }
  }, [stage])

  const begin = async () => {
    setError(null)
    try {
      for (const [kind, on] of [
        ['proctoring_biometric', bio],
        ['proctoring_photo', photo],
      ] as const) {
        if (!!me?.consents[kind] !== on) qc.setQueryData(['me'], await api.post<Me>('/api/me/consents', { kind, accepted: on }))
      }
      setStage('loading')
      await proctor.open()
      proctor.micPeak(true)
      setStage('check')
    } catch (e) {
      setStage('consent')
      setError(e instanceof DOMException && e.name === 'NotAllowedError' ? new Error('Браузер не дал доступ к камере или микрофону. Разрешите доступ в настройках сайта и попробуйте снова.') : e)
    }
  }

  const ready = !!res && res.camOk && res.light && res.faces === 1 && !res.phone && !!res.embedding && heard
  const liveOk = res?.real == null || res?.live == null ? null : res.real >= 0.4 && res.live >= 0.4

  const go = () => {
    const embeddings = proctor.startEmbeddings()
    if (!embeddings.length) return
    onReady({
      proctored: true,
      embeddings,
      embedding_model: proctor.model,
      snapshot: photo ? (proctor.snapshotJpeg() ?? undefined) : undefined,
    })
  }

  const cancel = () => {
    if (!proctor.active) proctor.stop()
    onClose()
  }

  return (
    <Modal open={open} onClose={cancel} title="Тест с цифровым проктором" wide>
      {stage === 'consent' ? (
        <div className="space-y-4 text-sm">
          <p className="text-ink-soft">
            Проктор подтверждает работодателю, что тест проходили вы и без посторонней помощи. Камера и микрофон анализируются <b>прямо в браузере</b>: видео и звук не записываются и не передаются. На сервер уходят только счётчики событий (нет лица в кадре, телефон, речь) и числовой отпечаток лица — для сверки с эталоном вашего профиля.
          </p>
          <ul className="grid gap-1.5 text-ink-soft sm:grid-cols-2">
            <li className="flex gap-2"><Smartphone className="mt-0.5 h-4 w-4 shrink-0 text-muted" />Телефон в кадре — нарушение</li>
            <li className="flex gap-2"><Users className="mt-0.5 h-4 w-4 shrink-0 text-muted" />В кадре — только вы</li>
            <li className="flex gap-2"><Mic className="mt-0.5 h-4 w-4 shrink-0 text-muted" />Микрофон включён, задания не читаем вслух</li>
            <li className="flex gap-2"><Camera className="mt-0.5 h-4 w-4 shrink-0 text-muted" />Лицо в кадре, достаточно света</li>
            <li className="flex gap-2 sm:col-span-2"><PenLine className="mt-0.5 h-4 w-4 shrink-0 text-muted" />Ручка и лист для расчётов — можно, смотреть на лист не нарушение. В тесте есть черновик и калькулятор</li>
          </ul>
          <label className="flex items-start gap-2.5 rounded-xl border border-line p-3">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-500" checked={bio} onChange={(e) => setBio(e.target.checked)} />
            <span>
              <b>Согласие на обработку биометрических данных</b> <span className="text-accent-500">*</span>
              <span className="mt-1 block text-xs text-muted">{config?.consent_texts.proctoring_biometric}</span>
            </span>
          </label>
          <label className="flex items-start gap-2.5 rounded-xl border border-line p-3">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-500" checked={photo} onChange={(e) => setPhoto(e.target.checked)} />
            <span>
              <b>Показать кадр с теста работодателю</b> <span className="text-xs text-muted">(по желанию)</span>
              <span className="mt-1 block text-xs text-muted">{config?.consent_texts.proctoring_photo}</span>
            </span>
          </label>
          <Notice>Без проктора тест тоже доступен — согласие добровольное. С проктором в карточке будет отметка «Тест с проктором», а в подборе работодателей вы будете стоять заметно выше: результату под наблюдением доверяют больше.</Notice>
          <ErrorBox error={error} />
          <div className="flex justify-end gap-2">
            <button className="btn-secondary" onClick={cancel}>
              Отмена
            </button>
            <button className="btn-primary" disabled={!bio} onClick={() => void begin()}>
              <Camera className="h-4 w-4" /> Включить камеру и микрофон
            </button>
          </div>
        </div>
      ) : stage === 'loading' ? (
        <div className="flex items-center gap-3 py-10 text-sm text-muted">
          <Loader2 className="h-5 w-5 animate-spin" /> Запускаем камеру и загружаем модели (один раз, ~15 МБ)…
        </div>
      ) : (
        <div className="grid gap-5 sm:grid-cols-[1.2fr_1fr]">
          <div>
            <div className="relative overflow-hidden rounded-xl">
              <SelfView className="aspect-[4/3] w-full" />
              <div className="absolute right-0 bottom-0 left-0 h-1.5 bg-ink/40">
                <div className="h-full bg-ok-600 transition-all" style={{ width: `${Math.round(live.level * 100)}%` }} />
              </div>
            </div>
            <p className="hint mt-2">Расположитесь так, чтобы лицо было по центру и хорошо освещено. Во время теста своего видео вы не увидите — только индикатор «вы в кадре».</p>
          </div>
          <div className="space-y-4">
            <ul className="space-y-2.5">
              <Check ok={!!res?.camOk && !!res?.light} pending={!res} hint="Откройте шторку камеры, добавьте света">
                Камера работает, света достаточно
              </Check>
              <Check ok={res?.faces === 1} pending={!res} hint={res && res.faces > 1 ? 'В кадре несколько человек' : 'Лицо не найдено — посмотрите в камеру'}>
                В кадре одно лицо
              </Check>
              <Check ok={!!res && !res.phone} pending={!res} hint="Уберите телефон из кадра">
                Телефона в кадре нет
              </Check>
              <Check ok={heard} hint="Скажите вслух «раз, два, три»">
                Микрофон слышит вас
              </Check>
              <Check ok={!!res?.embedding} pending={!res} hint="Сядьте ближе и посмотрите прямо в камеру">
                Отпечаток лица получен
              </Check>
            </ul>
            {liveOk === false && <Notice tone="warn">Похоже, в кадре фото или экран, а не живое лицо. Если это ошибка — поправьте свет и посмотрите в камеру.</Notice>}
            <ErrorBox error={error} />
            <div className="flex flex-wrap justify-end gap-2">
              <button className="btn-secondary" onClick={cancel}>
                Отмена
              </button>
              <button className="btn-primary" disabled={!ready} onClick={go}>
                <ShieldCheck className="h-4 w-4" /> Начать тест
              </button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  )
}

/**
 * Индикаторы проктора во время теста. Собственного видео нет намеренно: по нему легко найти слепые
 * зоны камеры (например, чтобы сфотографировать задание). Положение в кадре кандидат выставляет на
 * проверке перед стартом, а здесь видит только «вы в кадре / вас не видно».
 */
export function ProctorDock() {
  const live = useProctorLive()
  if (!live.active) return null
  const lost = live.faces === 0 && live.noFaceMs >= 3000
  const items = [
    { ok: live.camOk, icon: live.camOk ? Camera : VideoOff, label: live.camOk ? 'Камера' : 'Камера выключена' },
    { ok: live.micOk, icon: live.micOk ? Mic : MicOff, label: live.micOk ? 'Микрофон' : 'Микрофон выключен' },
    { ok: live.faces === 1, icon: live.faces > 1 ? Users : UserX, label: live.faces === 1 ? 'Вы в кадре' : live.faces > 1 ? 'Несколько лиц' : 'Вас не видно' },
    { ok: !live.phone, icon: Smartphone, label: live.phone ? 'Телефон в кадре' : 'Телефона нет' },
  ]
  return (
    <div
      className={clsx('fixed right-3 bottom-3 z-40 rounded-xl border bg-white shadow-lg transition-colors', lost ? 'border-accent-500 ring-2 ring-accent-500/30' : 'border-line')}
      aria-label="Цифровой проктор"
      aria-live="polite"
    >
      <div className="flex items-center gap-1 px-2 py-1.5">
        <ShieldCheck className="mr-0.5 h-3.5 w-3.5 text-muted" aria-hidden />
        {items.map(({ ok, icon: Icon, label }) => (
          <span key={label} title={label} aria-label={label} className={clsx('rounded-md p-1', ok ? 'text-ok-600' : 'bg-accent-50 text-accent-600')}>
            <Icon className="h-3.5 w-3.5" />
          </span>
        ))}
      </div>
      {lost && <div className="border-t border-accent-500/30 px-2.5 py-1 text-xs font-medium text-accent-600">Вас не видно в кадре</div>}
    </div>
  )
}

/** Бледный водяной знак с кодом кандидата и попытки: фото задания указывает на источник утечки. */
export function Watermark({ text }: { text: string }) {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='260' height='140'><text x='10' y='80' transform='rotate(-24 130 70)' font-family='monospace' font-size='13' fill='rgb(15,23,42)' fill-opacity='0.07'>${text}</text></svg>`
  return <div aria-hidden className="pointer-events-none absolute inset-0 z-10 select-none" style={{ backgroundImage: `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")` }} />
}
