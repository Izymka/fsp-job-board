// Окружение теста: полноэкранный режим (обязателен на десктопе), второй монитор, видеоадаптер
// (удалённый рабочий стол / виртуальная машина определяются на сервере по имени рендерера) и признак
// автоматизации браузера. Всё — сигналы для пометок, а не «детектор читерства».
import { useCallback, useEffect, useRef, useState } from 'react'

export interface TestEnv {
  renderer: string | null
  webdriver: boolean
  extended_screen: boolean | null
  desktop: boolean
  fullscreen: boolean
}

type ScreenExt = Screen & { isExtended?: boolean } & EventTarget

function webglRenderer(): string | null {
  try {
    const gl = document.createElement('canvas').getContext('webgl')
    if (!gl) return null
    const ext = gl.getExtension('WEBGL_debug_renderer_info')
    return String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER) ?? '') || null
  } catch {
    return null
  }
}

export const fullscreenSupported = () => typeof document.documentElement.requestFullscreen === 'function' && document.fullscreenEnabled
/** Десктоп с мышью: на телефонах и планшетах полноэкранный режим не требуется (на iPhone его нет). */
export const isDesktop = () => !window.matchMedia('(pointer: coarse)').matches && fullscreenSupported()
export const isFullscreen = () => !!document.fullscreenElement
export const screenExtended = (): boolean | null => {
  const v = (window.screen as ScreenExt).isExtended
  return typeof v === 'boolean' ? v : null
}

export function detectEnv(): TestEnv {
  return { renderer: webglRenderer(), webdriver: !!navigator.webdriver, extended_screen: screenExtended(), desktop: isDesktop(), fullscreen: isFullscreen() }
}

// Браузер отказал в полноэкранном режиме (встроенное окно, политика): тест не блокируется, а в ответах
// отмечается, что режим был недоступен — работодатель увидит пометку.
let denied = false
const listeners = new Set<() => void>()
export const fullscreenDenied = () => denied

const deny = (v: boolean) => {
  denied = v
  listeners.forEach((fn) => fn())
}
const ENTER_TIMEOUT_MS = 3000 // встроенные окна иногда не отвечают на запрос вовсе

/** Войти в полноэкранный режим. Вызывать синхронно в обработчике клика (требование браузера). */
export function enterFullscreen(): Promise<void> {
  if (!isDesktop() || isFullscreen()) return Promise.resolve()
  const timer = window.setTimeout(() => !isFullscreen() && deny(true), ENTER_TIMEOUT_MS)
  return document.documentElement.requestFullscreen({ navigationUI: 'hide' }).then(
    () => clearTimeout(timer),
    () => {
      clearTimeout(timer)
      deny(true)
    },
  )
}

export function exitFullscreen() {
  if (isFullscreen()) void document.exitFullscreen().catch(() => undefined)
}

const SHRINK = 0.85 // окно меньше 85% размера при входе в полноэкранный режим — что-то его потеснило

/**
 * Полноэкранный режим за задание: время вне него, число выходов, время с уменьшенным окном
 * (инструменты разработчика внутри полноэкранного режима), подключение второго монитора.
 */
export function useFullscreenGuard(itemKey: unknown, required: boolean) {
  const s = useRef({ offMs: 0, exits: 0, shrunkMs: 0, extended: false })
  const offSince = useRef<number | null>(null)
  const shrunkSince = useRef<number | null>(null)
  const base = useRef<{ w: number; h: number } | null>(isFullscreen() ? { w: window.innerWidth, h: window.innerHeight } : null)
  const [full, setFull] = useState(isFullscreen())
  const [extended, setExtended] = useState(!!screenExtended())
  const [unavailable, setUnavailable] = useState(denied)

  useEffect(() => {
    // новое задание — новые счётчики; текущие состояния (вне режима, окно уменьшено) отсчитываются заново
    s.current = { offMs: 0, exits: 0, shrunkMs: 0, extended: !!screenExtended() }
    const now = Date.now()
    if (offSince.current != null) offSince.current = now
    if (shrunkSince.current != null) shrunkSince.current = now
  }, [itemKey])

  useEffect(() => {
    if (!required) return
    // после перезагрузки страницы тест открывается не в полноэкранном режиме — время вне него идёт сразу
    if (!isFullscreen() && offSince.current == null) offSince.current = Date.now()
    const onChange = () => {
      const fs = isFullscreen()
      setFull(fs)
      if (fs) {
        if (denied) deny(false) // режим всё-таки включился — пометка не нужна
        if (offSince.current != null) s.current.offMs += Date.now() - offSince.current
        offSince.current = null
        base.current = { w: window.innerWidth, h: window.innerHeight }
      } else if (offSince.current == null) {
        offSince.current = Date.now()
        s.current.exits += 1
      }
    }
    const onResize = () => {
      const b = base.current
      const small = isFullscreen() && !!b && (window.innerWidth < b.w * SHRINK || window.innerHeight < b.h * SHRINK)
      if (small && shrunkSince.current == null) shrunkSince.current = Date.now()
      if (!small && shrunkSince.current != null) {
        s.current.shrunkMs += Date.now() - shrunkSince.current
        shrunkSince.current = null
      }
    }
    const scr = window.screen as ScreenExt
    const onScreen = () => {
      const ext = !!screenExtended()
      setExtended(ext)
      if (ext) s.current.extended = true
    }
    const onDenied = () => setUnavailable(denied)
    listeners.add(onDenied)
    document.addEventListener('fullscreenchange', onChange)
    window.addEventListener('resize', onResize)
    scr.addEventListener?.('change', onScreen)
    return () => {
      listeners.delete(onDenied)
      document.removeEventListener('fullscreenchange', onChange)
      window.removeEventListener('resize', onResize)
      scr.removeEventListener?.('change', onScreen)
    }
  }, [required])

  const snapshot = useCallback(() => {
    const now = Date.now()
    return {
      fullscreen_off_ms: denied ? 0 : s.current.offMs + (offSince.current != null ? now - offSince.current : 0),
      fullscreen_exits: s.current.exits,
      shrunk_ms: s.current.shrunkMs + (shrunkSince.current != null ? now - shrunkSince.current : 0),
      extended_screen: s.current.extended || !!screenExtended(),
      fullscreen_unavailable: required && denied,
    }
  }, [required])

  // режим недоступен — не блокируем тест (время вне режима не считается уходом), но отмечаем это
  return { full: !required || full || unavailable, extended, unavailable: required && unavailable, snapshot }
}
