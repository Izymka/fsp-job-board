import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Building2, Check, Mail, X } from 'lucide-react'
import { useState } from 'react'
import { StatusBadge } from '../../components/domain'
import { Badge, EmptyState, ErrorBox, Field, Modal, Notice, PageHeader, PageLoader, Tabs } from '../../components/ui'
import { api } from '../../lib/api'
import { date, lookup, pct, range, useCatalog } from '../../lib/catalog'
import type { Invitation } from '../../lib/types'

const METHOD: Record<string, string> = { email: 'Email', telegram: 'Telegram', phone: 'Телефон', other: 'Другое' }

function InvitationDetail({ inv, onClose }: { inv: Invitation; onClose: () => void }) {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const qc = useQueryClient()
  const [declining, setDeclining] = useState(false)
  const [reason, setReason] = useState('salary')
  const [comment, setComment] = useState('')
  const { data: full } = useQuery({ queryKey: ['invitation', inv.id], queryFn: () => api.get<Invitation>(`/api/candidate/invitations/${inv.id}`) })
  const i = full ?? inv
  const done = () => {
    qc.invalidateQueries({ queryKey: ['candidate-invitations'] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const accept = useMutation({ mutationFn: () => api.post<Invitation>(`/api/candidate/invitations/${inv.id}/accept`), onSuccess: (d) => (qc.setQueryData(['invitation', inv.id], d), done()) })
  const decline = useMutation({ mutationFn: () => api.post<Invitation>(`/api/candidate/invitations/${inv.id}/decline`, { reason, comment: comment || null }), onSuccess: (d) => (qc.setQueryData(['invitation', inv.id], d), done(), setDeclining(false)) })
  const active = i.status === 'sent' || i.status === 'viewed'
  return (
    <Modal open onClose={onClose} title={i.title} wide>
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={i.status} />
          <span className="text-sm text-muted">получено {date(i.created_at)}</span>
        </div>
        <div className="grid gap-4 sm:grid-cols-[1fr_15rem]">
          <div>
            <div className="flex items-center gap-2 font-medium">
              <Building2 className="h-4 w-4 text-brand-500" /> {i.company_name}
              {i.company_industry && <Badge>{L.industry(i.company_industry)}</Badge>}
            </div>
            {i.company_description && <p className="mt-1 text-sm text-muted">{i.company_description}</p>}
            <p className="mt-4 text-sm whitespace-pre-wrap">{i.description}</p>
          </div>
          <div className="space-y-3">
            <div className="rounded-xl bg-brand-50 p-4">
              <div className="text-xs text-brand-700">Зарплата</div>
              <div className="font-mono text-xl font-bold text-brand-600">{range(i.salary_from, i.salary_to)}</div>
            </div>
            {i.company_stats && (
              <div className="rounded-xl border border-line p-4 text-xs text-muted">
                <div className="mb-1 font-medium text-ink">О компании на платформе</div>
                Приглашений за 90 дней: {i.company_stats.invitations_90d}
                <br />
                Кандидаты принимают: {pct(i.company_stats.acceptance_rate)}
                <br />
                Отвечает на отклики: {pct(i.company_stats.application_response_rate)}
              </div>
            )}
          </div>
        </div>
        {i.status === 'accepted' && (
          <Notice tone="ok">
            Вы приняли приглашение. Связь: {METHOD[i.contact_method]} — <b>{i.contact_value}</b>. Компания видит ваши контакты.
          </Notice>
        )}
        {i.status === 'declined' && <Notice tone="warn">Вы отклонили приглашение: {L.reason(i.decline_reason)}.</Notice>}
        {active && !declining && (
          <div className="flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center">
            <p className="flex-1 text-xs text-muted">Если примете — компания увидит ваше ФИО и контакты и свяжется удобным способом: {METHOD[i.contact_method]}.</p>
            <button className="btn-secondary" onClick={() => setDeclining(true)}>
              <X className="h-4 w-4" /> Отклонить
            </button>
            <button className="btn-primary" onClick={() => accept.mutate()} disabled={accept.isPending}>
              <Check className="h-4 w-4" /> Принять
            </button>
          </div>
        )}
        {declining && (
          <div className="space-y-3 border-t border-line pt-4">
            <span className="label">Причина отказа — компания увидит её в агрегированной статистике</span>
            <div className="flex flex-wrap gap-2">
              {cat?.decline_reasons.map((r) => (
                <button key={r.id} type="button" onClick={() => setReason(r.id)} className={clsx('chip border px-3 py-1.5 text-sm', reason === r.id ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink-soft')}>
                  {r.title}
                </button>
              ))}
            </div>
            <Field label="Комментарий (необязательно)">
              <textarea className="input min-h-16" value={comment} onChange={(e) => setComment(e.target.value)} />
            </Field>
            <div className="flex gap-2">
              <button className="btn-danger" onClick={() => decline.mutate()} disabled={decline.isPending}>
                Отклонить приглашение
              </button>
              <button className="btn-ghost" onClick={() => setDeclining(false)}>
                Отмена
              </button>
            </div>
          </div>
        )}
        <ErrorBox error={accept.error || decline.error} />
      </div>
    </Modal>
  )
}

export default function CandidateInvitations() {
  const [tab, setTab] = useState<'active' | 'all'>('active')
  const [open, setOpen] = useState<Invitation | null>(null)
  const invs = useQuery({ queryKey: ['candidate-invitations'], queryFn: () => api.get<Invitation[]>('/api/candidate/invitations') })
  const data = invs.data
  if (!data) return <PageLoader queries={[invs]} />
  const rows = tab === 'active' ? data.filter((i) => i.status === 'sent' || i.status === 'viewed') : data
  return (
    <div>
      <PageHeader title="Приглашения от работодателей" />
      <Tabs value={tab} onChange={setTab} items={[{ id: 'active', label: `Ожидают ответа (${data.filter((i) => i.status === 'sent' || i.status === 'viewed').length})` }, { id: 'all', label: `Все (${data.length})` }]} />
      {rows.length === 0 ? (
        <EmptyState icon={<Mail className="h-6 w-6" />} title="Пока нет приглашений" text="Работодатели находят кандидатов в категориях после подтверждения грейда. Поддерживайте профиль актуальным — решайте регулярные задания." />
      ) : (
        <div className="grid gap-3">
          {rows.map((i) => (
            <button key={i.id} onClick={() => setOpen(i)} className={clsx('card flex flex-col gap-3 p-5 text-left transition-colors hover:border-brand-300 sm:flex-row sm:items-center', i.status === 'sent' && 'border-brand-300')}>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-bold">{i.title}</span>
                  {i.status === 'sent' && <Badge tone="bg-brand-500 text-white">новое</Badge>}
                </div>
                <div className="mt-1 text-sm text-muted">
                  {i.company_name} · {date(i.created_at)}
                </div>
              </div>
              <div className="font-mono text-lg font-bold text-brand-600">{range(i.salary_from, i.salary_to)}</div>
              <StatusBadge status={i.status} />
            </button>
          ))}
        </div>
      )}
      {open && <InvitationDetail inv={open} onClose={() => setOpen(null)} />}
    </div>
  )
}
