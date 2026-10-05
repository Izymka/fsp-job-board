import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Building2, UserRound } from 'lucide-react'
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ErrorBox, PageLoader } from '../../components/ui'
import { api } from '../../lib/api'
import { useAuth, useMe } from '../../lib/auth'
import type { Me, Role } from '../../lib/types'

export default function Onboarding() {
  const { ready, authenticated, config, login } = useAuth()
  const { data: me, isLoading } = useMe()
  const qc = useQueryClient()
  const nav = useNavigate()
  const intent = (typeof localStorage !== 'undefined' && (localStorage.getItem('fsp_intent') as Role | null)) || null
  const [role, setRole] = useState<Role | null>(intent)
  const [pd, setPd] = useState(false)
  const [pub, setPub] = useState(true)
  const m = useMutation({
    mutationFn: () => api.post<Me>('/api/me/role', { role, accept_pd_processing: pd, accept_profile_publication: role === 'candidate' ? pub : false }),
    onSuccess: (data) => {
      qc.setQueryData(['me'], data)
      localStorage.removeItem('fsp_intent')
      nav(data.role === 'candidate' ? '/candidate/survey' : '/employer/company')
    },
  })
  if (!ready || isLoading) return <PageLoader />
  if (!authenticated) {
    login('/onboarding')
    return <PageLoader />
  }
  if (me?.role) return <Navigate to="/app" replace />
  const texts = config?.consent_texts ?? {}
  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-1 font-mono text-xs tracking-wider text-brand-500 uppercase">Шаг 1 из 3</div>
      <h1 className="text-3xl font-bold">Кто вы на платформе?</h1>
      <p className="mt-2 text-muted">Роль выбирается один раз. Для другой роли используйте отдельную учётную запись.</p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {[
          { id: 'candidate' as Role, icon: UserRound, title: 'Ищу работу', text: 'Пройду опрос и тест, получу категорию и приглашения с зарплатой.' },
          { id: 'employer' as Role, icon: Building2, title: 'Ищу специалистов', text: 'Опишу потребность, получу подборку с объяснением и приглашу кандидатов.' },
        ].map((r) => (
          <button
            key={r.id}
            onClick={() => setRole(r.id)}
            className={clsx('card flex gap-4 p-5 text-left transition-all', role === r.id ? 'border-brand-500 ring-4 ring-brand-100' : 'hover:border-brand-300')}
            aria-pressed={role === r.id}
          >
            <div className={clsx('flex h-12 w-12 shrink-0 items-center justify-center rounded-xl', role === r.id ? 'bg-brand-500 text-white' : 'bg-brand-50 text-brand-500')}>
              <r.icon className="h-6 w-6" />
            </div>
            <div>
              <div className="font-mono text-lg font-bold">{r.title}</div>
              <p className="mt-1 text-sm text-muted">{r.text}</p>
            </div>
          </button>
        ))}
      </div>

      <div className="card mt-6 space-y-4 p-5">
        <label className="flex gap-3 text-sm">
          <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-500" checked={pd} onChange={(e) => setPd(e.target.checked)} />
          <span>
            <span className="font-medium">Согласие на обработку персональных данных</span> <span className="text-accent-500">*</span>
            <span className="mt-1 block text-muted">{texts.pd_processing}</span>
          </span>
        </label>
        {role === 'candidate' && (
          <label className="flex gap-3 text-sm">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-500" checked={pub} onChange={(e) => setPub(e.target.checked)} />
            <span>
              <span className="font-medium">Согласие на публикацию обезличенного профиля для работодателей</span>
              <span className="mt-1 block text-muted">{texts.profile_publication} Без этого согласия работодатели не увидят вас в поиске — его можно дать позже в настройках.</span>
            </span>
          </label>
        )}
        <div className="text-xs text-muted">Версия согласия: {config?.consent_version}. Согласие можно отозвать в настройках.</div>
      </div>
      <div className="mt-5 flex items-center gap-3">
        <button className="btn-primary px-6" disabled={!role || !pd || m.isPending} onClick={() => m.mutate()}>
          Продолжить
        </button>
        {!pd && <span className="text-sm text-muted">Нужно согласие на обработку данных</span>}
      </div>
      <div className="mt-3">
        <ErrorBox error={m.error} />
      </div>
    </div>
  )
}
