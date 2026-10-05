import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ErrorBox, Notice, PageLoader } from '../../components/ui'
import { errorText } from '../../lib/api'
import { useAuth } from '../../lib/auth'

const DEMO = [
  { email: 'employer@demo.fsp', label: 'Работодатель «Рубль+»' },
  { email: 'maria@demo.fsp', label: 'Кандидат с категорией и ФСП' },
  { email: 'candidate@demo.fsp', label: 'Новый кандидат (онбординг)' },
]

/** Вход без Keycloak — только когда бэкенд запущен в AUTH_MODE=dev (локальная отладка). */
export default function DevLogin() {
  const { config, ready, devLogin, login } = useAuth()
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const nav = useNavigate()
  if (!ready) return <PageLoader />
  if (config?.mode !== 'dev') {
    login()
    return <PageLoader />
  }
  const go = async (e: string) => {
    setError(null)
    try {
      await devLogin(e)
      nav('/app')
    } catch (err) {
      setError(errorText(err))
    }
  }
  if (!config) return <Navigate to="/" />
  return (
    <div className="mx-auto max-w-md">
      <h1 className="text-2xl font-bold">Вход (режим разработки)</h1>
      <div className="mt-3">
        <Notice tone="warn">Бэкенд запущен с AUTH_MODE=dev: вход без пароля, только для локальной отладки. В рабочем режиме вход и регистрация — через Keycloak с подтверждением email.</Notice>
      </div>
      <form
        className="card mt-5 space-y-3 p-5"
        onSubmit={(e) => {
          e.preventDefault()
          go(email)
        }}
      >
        <label className="label" htmlFor="email">
          Email
        </label>
        <input id="email" className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.ru" />
        <button className="btn-primary w-full">Войти</button>
        <ErrorBox error={error} />
      </form>
      <div className="mt-5 space-y-2">
        <div className="text-sm text-muted">Демо-аккаунты:</div>
        {DEMO.map((d) => (
          <button key={d.email} className="btn-secondary w-full justify-between" onClick={() => go(d.email)}>
            <span>{d.label}</span>
            <span className="font-mono text-xs text-muted">{d.email}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
