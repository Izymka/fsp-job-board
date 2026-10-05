import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Link2, RefreshCw, Unlink } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { FspList } from '../../components/domain'
import { ErrorBox, Notice, PageHeader, PageLoader, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { useAuth, useMe } from '../../lib/auth'
import { date, dateTime, useCatalog } from '../../lib/catalog'
import type { Me, Profile } from '../../lib/types'

const FSP_MSG: Record<string, { text: string; tone: 'ok' | 'warn' }> = {
  linked: { text: 'ФСП ID привязан, достижения загружены из реестра.', tone: 'ok' },
  cancelled: { text: 'Привязка отменена.', tone: 'warn' },
  fsp_id_taken: { text: 'Этот ФСП ID уже привязан к другому профилю.', tone: 'warn' },
  invalid_state: { text: 'Сессия привязки устарела — попробуйте ещё раз.', tone: 'warn' },
  error: { text: 'Не удалось привязать ФСП ID. Попробуйте позже.', tone: 'warn' },
}

export default function CandidateSettings() {
  const { data: cat } = useCatalog()
  const { config } = useAuth()
  const { data: me } = useMe()
  const qc = useQueryClient()
  const [params] = useSearchParams()
  const fspMsg = FSP_MSG[params.get('fsp') ?? '']
  const { data: p } = useQuery({ queryKey: ['profile'], queryFn: () => api.get<Profile>('/api/candidate/profile') })
  const [showFsp, setShowFsp] = useState(true)
  const [excluded, setExcluded] = useState<string[]>([])
  const [status, setStatus] = useState('active')
  const [demoId, setDemoId] = useState('FSP-000123')
  useEffect(() => {
    if (!p) return
    setShowFsp(p.show_fsp)
    setExcluded(p.excluded_industries)
    setStatus(p.search_status)
  }, [p])
  const onProfile = (d: Profile) => {
    qc.setQueryData(['profile'], d)
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const privacy = useMutation({ mutationFn: () => api.put<Profile>('/api/candidate/privacy', { show_fsp: showFsp, excluded_industries: excluded, excluded_companies: p?.excluded_companies ?? [], search_status: status }), onSuccess: onProfile })
  const link = useMutation({
    mutationFn: async () => {
      if (config?.mode === 'dev') return onProfile(await api.post<Profile>('/api/fsp/link/demo', { fsp_id: demoId }))
      const r = await api.get<{ authorize_url: string }>('/api/fsp/link/start')
      window.location.href = r.authorize_url
    },
  })
  const sync = useMutation({ mutationFn: () => api.post<Profile>('/api/fsp/sync'), onSuccess: onProfile })
  const unlink = useMutation({ mutationFn: () => api.del<Profile>('/api/fsp/link'), onSuccess: onProfile })
  const consent = useMutation({
    mutationFn: (v: { kind: string; accepted: boolean }) => api.post<Me>('/api/me/consents', v),
    onSuccess: (d) => {
      qc.setQueryData(['me'], d)
      qc.invalidateQueries({ queryKey: ['profile'] })
    },
  })
  if (!p || !cat || !me) return <PageLoader />
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader eyebrow="Настройки" title="Приватность, ФСП ID и согласия" />
      {fspMsg && <Notice tone={fspMsg.tone}>{fspMsg.text}</Notice>}

      <Section title="ФСП ID">
        {p.fsp_id ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm">
                Привязан <b className="font-mono">{p.fsp_id}</b>
                {p.fsp_profile?.sport_rank && <span className="text-muted"> · разряд: {p.fsp_profile.sport_rank}</span>}
                <div className="text-xs text-muted">
                  с {date(p.fsp_linked_at)} · синхронизация {dateTime(p.fsp_synced_at)}
                </div>
              </div>
              <div className="flex gap-2">
                <button className="btn-secondary btn-sm" onClick={() => sync.mutate()} disabled={sync.isPending}>
                  <RefreshCw className={clsx('h-3.5 w-3.5', sync.isPending && 'animate-spin')} /> Обновить
                </button>
                <button className="btn-danger btn-sm" onClick={() => window.confirm('Отвязать ФСП ID? Достижения перестанут отображаться.') && unlink.mutate()}>
                  <Unlink className="h-3.5 w-3.5" /> Отвязать
                </button>
              </div>
            </div>
            <FspList items={p.fsp_achievements} linked visible />
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted">Войдите в ФСП ID — платформа получит ваш идентификатор участника и подтянет результаты соревнований из реестра ФСП. Если истории нет — ничего страшного: профиль ранжируется по тесту.</p>
            {config?.mode === 'dev' && (
              <div className="flex items-center gap-2">
                <input className="input w-44 font-mono" value={demoId} onChange={(e) => setDemoId(e.target.value)} />
                <span className="text-xs text-muted">демо-режим: FSP-000123 — с достижениями, FSP-000999 — без истории</span>
              </div>
            )}
            <button className="btn-primary" onClick={() => link.mutate()} disabled={link.isPending}>
              <Link2 className="h-4 w-4" /> Привязать ФСП ID
            </button>
          </div>
        )}
        <ErrorBox error={link.error || sync.error || unlink.error} />
      </Section>

      <Section title="Что видит работодатель">
        <ul className="mb-4 space-y-1 text-sm text-muted">
          <li>• До контакта: категория, навыки и их подтверждение, стек, опыт, город, формат — без ФИО и контактов.</li>
          <li>• После принятия приглашения или вашего отклика: ФИО и контакты.</li>
          <li>• Ожидания по зарплате не раскрываются — работодатель видит только, укладывается ли его вилка.</li>
        </ul>
        <div className="space-y-4">
          <label className="flex items-center gap-3 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={showFsp} onChange={(e) => setShowFsp(e.target.checked)} />
            Показывать достижения ФСП работодателям (скрытые не учитываются и в ранжировании)
          </label>
          <div>
            <span className="label">Скрыть профиль от компаний отраслей</span>
            <div className="flex flex-wrap gap-2">
              {cat.industries.map((i) => (
                <button key={i.id} type="button" onClick={() => setExcluded(excluded.includes(i.id) ? excluded.filter((x) => x !== i.id) : [...excluded, i.id])} className={clsx('chip border px-3 py-1.5 text-sm', excluded.includes(i.id) ? 'border-accent-500 bg-accent-50 text-accent-600' : 'border-line text-ink-soft')}>
                  {i.title}
                </button>
              ))}
            </div>
            <p className="hint">Например, чтобы текущий работодатель не увидел, что вы ищете работу.</p>
          </div>
          <div>
            <span className="label">Статус поиска</span>
            <div className="flex flex-wrap gap-2">
              {cat.search_statuses.map((s) => (
                <button key={s.id} type="button" onClick={() => setStatus(s.id)} className={clsx('chip border px-3 py-1.5 text-sm', status === s.id ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink-soft')}>
                  {s.title}
                </button>
              ))}
            </div>
          </div>
          <button className="btn-primary" onClick={() => privacy.mutate()} disabled={privacy.isPending}>
            Сохранить
          </button>
          {privacy.isSuccess && <span className="ml-3 text-sm text-ok-600">Сохранено</span>}
          <ErrorBox error={privacy.error} />
        </div>
      </Section>

      <Section title="Согласия (152-ФЗ)">
        <div className="space-y-3 text-sm">
          {[
            { kind: 'pd_processing', title: 'Обработка персональных данных', note: 'Без него работа с платформой невозможна; отзыв скрывает профиль.' },
            { kind: 'profile_publication', title: 'Публикация обезличенного профиля для работодателей', note: 'Без него вы не появляетесь в поиске.' },
          ].map((c) => (
            <div key={c.kind} className="flex flex-col justify-between gap-2 rounded-xl border border-line p-3 sm:flex-row sm:items-center">
              <div>
                <div className="font-medium">{c.title}</div>
                <div className="text-xs text-muted">{c.note}</div>
              </div>
              {me.consents[c.kind] ? (
                <button className="btn-danger btn-sm" onClick={() => consent.mutate({ kind: c.kind, accepted: false })}>
                  Отозвать
                </button>
              ) : (
                <button className="btn-primary btn-sm" onClick={() => consent.mutate({ kind: c.kind, accepted: true })}>
                  Дать согласие
                </button>
              )}
            </div>
          ))}
          {p.hidden && <Notice tone="warn">Профиль скрыт от работодателей: нет согласия на публикацию.</Notice>}
        </div>
      </Section>
    </div>
  )
}
