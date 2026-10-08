// Авторизация: Keycloak (OIDC, PKCE) — совместимо с будущим ФСП ID.
// Режим dev (AUTH_MODE=dev на бэкенде) — вход по email без Keycloak, только для локальной отладки.
import Keycloak from 'keycloak-js'
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { EmptyState, PageLoader } from '../components/ui'
import { ApiError, api, setTokenProvider } from './api'
import type { AuthConfig, Me } from './types'

const DEV_KEY = 'fsp_dev_token'

interface AuthState {
  config: AuthConfig | null
  ready: boolean
  authenticated: boolean
  login: (redirectTo?: string) => void
  register: () => void
  logout: () => void
  devLogin: (email: string) => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)

function readDevToken(): string | null {
  try {
    return localStorage.getItem(DEV_KEY)
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [ready, setReady] = useState(false)
  const [authenticated, setAuthenticated] = useState(false)
  const kcRef = useRef<Keycloak | null>(null)
  const qc = useQueryClient()

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      let cfg: AuthConfig
      try {
        cfg = await api.get<AuthConfig>('/api/auth/config')
      } catch {
        cfg = { mode: 'dev', keycloak_url: '', realm: '', client_id: '', consent_version: '', consent_texts: {} }
      }
      if (cancelled) return
      setConfig(cfg)
      if (cfg.mode === 'dev') {
        setTokenProvider(async () => readDevToken())
        setAuthenticated(!!readDevToken())
        setReady(true)
        return
      }
      const kc = new Keycloak({ url: cfg.keycloak_url, realm: cfg.realm, clientId: cfg.client_id })
      kcRef.current = kc
      setTokenProvider(async () => {
        if (!kc.authenticated) return null
        try {
          await kc.updateToken(30)
        } catch {
          kc.login()
        }
        return kc.token ?? null
      })
      try {
        const ok = await kc.init({
          onLoad: 'check-sso',
          pkceMethod: 'S256',
          // Проверка SSO редиректом (prompt=none), без скрытого iframe: работает при строгих
          // CSP/frame-ancestors Keycloak и блокировке сторонних cookie в браузере.
          checkLoginIframe: false,
        })
        if (!cancelled) setAuthenticated(ok)
      } catch {
        if (!cancelled) setAuthenticated(false)
      }
      kc.onAuthLogout = () => setAuthenticated(false)
      if (!cancelled) setReady(true)
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      config,
      ready,
      authenticated,
      login: (redirectTo?: string) => {
        if (config?.mode === 'dev') {
          window.location.href = '/login'
          return
        }
        kcRef.current?.login({ redirectUri: window.location.origin + (redirectTo ?? '/app') })
      },
      register: () => {
        if (config?.mode === 'dev') {
          window.location.href = '/login'
          return
        }
        kcRef.current?.register({ redirectUri: window.location.origin + '/app' })
      },
      logout: () => {
        qc.clear()
        if (config?.mode === 'dev') {
          localStorage.removeItem(DEV_KEY)
          setAuthenticated(false)
          window.location.href = '/'
          return
        }
        kcRef.current?.logout({ redirectUri: window.location.origin + '/' })
      },
      devLogin: async (email: string) => {
        const r = await api.post<{ access_token: string }>('/api/dev/login', { email })
        localStorage.setItem(DEV_KEY, r.access_token)
        qc.clear()
        setAuthenticated(true)
      },
    }),
    [config, ready, authenticated, qc],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('AuthProvider missing')
  return v
}

export function useMe() {
  const { authenticated, ready } = useAuth()
  return useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<Me>('/api/me'),
    enabled: ready && authenticated,
    staleTime: 30_000,
    // 401 повтором не исправить — сразу показываем «Сессия истекла»
    retry: (n, e) => !(e instanceof ApiError && e.status === 401) && n < 1,
  })
}

const isUnauthorized = (e: unknown) => e instanceof ApiError && e.status === 401

// Токен есть, но /api/me не ответил: 401 — сессия истекла или токен недействителен (например,
// пересоздана база или сменился секрет dev-режима) — предлагаем войти заново; иначе — сбой с повтором.
// Результат запроса передаётся снаружи: собственный useMe() здесь перезапрашивал бы упавший запрос
// при каждом монтировании, и Gate зацикливался бы между спиннером и этим экраном.
export function MeLoadError({ me, redirectTo }: { me: ReturnType<typeof useMe>; redirectTo: string }) {
  const { login } = useAuth()
  if (isUnauthorized(me.error))
    return (
      <EmptyState
        title="Сессия истекла"
        text="Войдите снова, чтобы продолжить."
        action={
          <button className="btn-primary" onClick={() => login(redirectTo)}>
            Войти
          </button>
        }
      />
    )
  return <PageLoader queries={[me]} />
}
