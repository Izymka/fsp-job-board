import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { BadgeCheck, CircleAlert, CircleMinus, Medal, Pin, PinOff, Send } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { INVITE_STATUS, SALARY_FIT, SKILL_STATUS, date, lookup, pct, useCatalog } from '../lib/catalog'
import type { CandidateCard, FspAchievement, Invitation, Ranked, Reason, SkillScore } from '../lib/types'
import { Badge, ErrorBox, Field, Modal, Notice } from './ui'

export function BlueprintBars({ blueprint, label }: { blueprint: Record<string, number>; label: (k: string) => string }) {
  const rows = Object.entries(blueprint).sort((a, b) => b[1] - a[1])
  const max = Math.max(...rows.map((r) => r[1]), 0.01)
  return (
    <div className="space-y-2">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[minmax(0,10rem)_1fr_3rem] items-center gap-3 text-sm">
          <span className="truncate text-ink-soft" title={label(k)}>
            {label(k)}
          </span>
          <div className="h-2.5 overflow-hidden rounded-full bg-fog">
            <div className="h-full rounded-full bg-brand-500" style={{ width: `${(v / max) * 100}%` }} />
          </div>
          <span className="text-right font-mono text-xs text-muted">{Math.round(v * 100)}%</span>
        </div>
      ))}
    </div>
  )
}

export function StatusBadge({ status, map = INVITE_STATUS }: { status: string; map?: Record<string, { label: string; tone: string }> }) {
  const s = map[status] ?? { label: status, tone: 'bg-surface text-muted' }
  return <Badge tone={s.tone}>{s.label}</Badge>
}

export function SalaryFit({ fit }: { fit?: string | null }) {
  if (!fit) return null
  const s = SALARY_FIT[fit] ?? SALARY_FIT.unknown
  return <Badge tone={s.tone}>{s.label}</Badge>
}

const REASON_ICON = { positive: BadgeCheck, neutral: CircleMinus, negative: CircleAlert }
const REASON_TONE = { positive: 'text-ok-600', neutral: 'text-muted', negative: 'text-accent-600' }

export function Reasons({ reasons, compact }: { reasons: Reason[]; compact?: boolean }) {
  return (
    <ul className={clsx('grid gap-1.5', compact ? 'text-xs' : 'text-sm')}>
      {reasons.map((r, i) => {
        const Icon = REASON_ICON[r.kind]
        return (
          <li key={i} className="flex items-start gap-2">
            <Icon className={clsx('mt-0.5 h-4 w-4 shrink-0', REASON_TONE[r.kind])} />
            <span className={r.kind === 'negative' ? 'text-accent-600' : 'text-ink-soft'}>{r.text}</span>
          </li>
        )
      })}
    </ul>
  )
}

const COMPONENT_LABEL: Record<string, string> = {
  need_fit: 'Соответствие потребности',
  profile: 'Сила профиля',
  conditions: 'Условия',
  freshness: 'Свежесть',
}
const COMPONENT_COLOR: Record<string, string> = {
  need_fit: 'bg-brand-500',
  profile: 'bg-brand-300',
  conditions: 'bg-ok-600',
  freshness: 'bg-steel',
}

export function ScoreBar({ score, components }: { score: number; components: Record<string, number> }) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-xs text-muted">Соответствие</span>
        <span className="font-mono text-lg font-bold text-brand-600">{Math.round(score * 100)}</span>
      </div>
      <div className="flex h-2 overflow-hidden rounded-full bg-fog" title="Вклад компонентов в итоговый скор">
        {Object.entries(components).map(([k, v]) => (
          <div key={k} className={COMPONENT_COLOR[k] ?? 'bg-steel'} style={{ width: `${v * 100}%` }} />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted">
        {Object.entries(components).map(([k, v]) => (
          <span key={k} className="inline-flex items-center gap-1">
            <span className={clsx('h-2 w-2 rounded-full', COMPONENT_COLOR[k])} />
            {COMPONENT_LABEL[k] ?? k} {Math.round(v * 100)}
          </span>
        ))}
      </div>
    </div>
  )
}

export function SkillList({ scores }: { scores: Record<string, SkillScore | string> }) {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const order = ['confirmed', 'uncertain', 'weak', 'no_data']
  const rows = Object.entries(scores)
    .map(([k, v]) => ({ k, status: typeof v === 'string' ? v : v.status, n: typeof v === 'string' ? undefined : v.n }))
    .sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status))
  return (
    <ul className="grid gap-1.5 sm:grid-cols-2">
      {rows.map((r) => {
        const s = SKILL_STATUS[r.status] ?? SKILL_STATUS.no_data
        return (
          <li key={r.k} className="flex items-center justify-between gap-2 rounded-lg bg-surface px-3 py-2 text-sm">
            <span className="flex items-center gap-2">
              <span className={clsx('h-2 w-2 rounded-full', s.dot)} />
              {L.skill(r.k)}
            </span>
            <span className="text-xs text-muted">
              {s.label}
              {r.n ? ` · ${r.n}` : ''}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

export function FspList({ items, linked, visible = true }: { items: FspAchievement[]; linked: boolean; visible?: boolean }) {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  if (!linked) return <p className="text-sm text-muted">ФСП ID не привязан — это не влияет на категорию, профиль ранжируется по результатам теста.</p>
  if (!visible) return <p className="text-sm text-muted">Достижения скрыты настройками приватности.</p>
  if (!items.length) return <p className="text-sm text-muted">ФСП ID привязан, достижений в реестре пока нет.</p>
  return (
    <ul className="space-y-2">
      {items.map((a, i) => (
        <li key={a.id ?? i} className="flex gap-3 rounded-xl border border-line p-3">
          <div className={clsx('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg', a.result === 'winner' || a.result === 'prize' ? 'bg-accent-50 text-accent-500' : 'bg-brand-50 text-brand-500')}>
            <Medal className="h-5 w-5" />
          </div>
          <div className="min-w-0 text-sm">
            <div className="font-medium">{a.title}</div>
            <div className="text-xs text-muted">
              {L.fspResult(a.result)}
              {a.place ? ` (${a.place} место)` : ''} · {L.fspLevel(a.level)} · {date(a.date)}
              {a.role ? ` · роль: ${a.role}` : ''}
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}

export function CandidateRow({ r, onInvite, onPin, searchHref }: { r: Ranked; onInvite?: () => void; onPin?: () => void; searchHref?: string }) {
  const c = r.card
  return (
    <article className="card p-5">
      <div className="flex flex-col gap-5 md:flex-row">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link to={`/employer/candidates/${c.id}${searchHref ?? ''}`} className="font-mono text-base font-bold hover:text-brand-600">
              {c.revealed && c.full_name ? c.full_name : c.alias}
            </Link>
            <Badge tone="bg-brand-50 text-brand-700">{c.category} ✓</Badge>
            {r.adjacent && <Badge tone="bg-warn-50 text-warn-600">соседняя категория</Badge>}
            {c.revealed && <Badge tone="bg-ok-50 text-ok-600">контакты открыты</Badge>}
          </div>
          <div className="mt-1 text-sm text-muted">
            {[c.headline, c.city, c.experience_years != null ? `опыт ${c.experience_years} г.` : null].filter(Boolean).join(' · ')}
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {c.stack.slice(0, 10).map((s) => (
              <Badge key={s} tone="bg-surface text-ink-soft">
                {s}
              </Badge>
            ))}
          </div>
          <div className="mt-4">
            <Reasons reasons={r.reasons} compact />
          </div>
        </div>
        <div className="flex w-full shrink-0 flex-col gap-3 md:w-64">
          <ScoreBar score={r.score} components={r.components} />
          <div className="mt-auto flex gap-2">
            {onInvite && (
              <button className="btn-primary flex-1" onClick={onInvite}>
                <Send className="h-4 w-4" /> Пригласить
              </button>
            )}
            {onPin && (
              <button className={clsx('btn-secondary px-3', r.shortlisted && 'border-brand-500 text-brand-600')} onClick={onPin} title={r.shortlisted ? 'Убрать из шорт-листа' : 'В шорт-лист'} aria-label="Шорт-лист">
                {r.shortlisted ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
              </button>
            )}
          </div>
        </div>
      </div>
    </article>
  )
}

export function CandidateMini({ c, right }: { c: CandidateCard; right?: ReactNode }) {
  return (
    <div className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/employer/candidates/${c.id}`} className="font-mono font-bold hover:text-brand-600">
            {c.revealed && c.full_name ? c.full_name : c.alias}
          </Link>
          <Badge tone="bg-brand-50 text-brand-700">{c.category}</Badge>
          {c.fsp.length > 0 && <Badge tone="bg-accent-50 text-accent-600">ФСП · {c.fsp.length}</Badge>}
        </div>
        <div className="mt-1 text-xs text-muted">
          {[c.headline, c.city, c.test_percentile != null ? `тест: ${pct(c.test_percentile)} перцентиль` : null, c.last_active_days != null ? `активен ${c.last_active_days} дн. назад` : null].filter(Boolean).join(' · ')}
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {c.confirmed_skills.slice(0, 6).map((s) => (
            <Badge key={s} tone="bg-ok-50 text-ok-600">
              {s} ✓
            </Badge>
          ))}
        </div>
      </div>
      {right}
    </div>
  )
}

export function InviteModal({ candidate, searchId, open, onClose, defaults }: { candidate: { id: string; label: string } | null; searchId?: string; open: boolean; onClose: () => void; defaults?: { title?: string; salary_from?: number | null; salary_to?: number | null } }) {
  const qc = useQueryClient()
  const [title, setTitle] = useState(defaults?.title ?? '')
  const [description, setDescription] = useState('')
  const [from, setFrom] = useState(defaults?.salary_from ? String(defaults.salary_from) : '')
  const [to, setTo] = useState(defaults?.salary_to ? String(defaults.salary_to) : '')
  const [method, setMethod] = useState('email')
  const [contact, setContact] = useState('')
  const sf = Number(from)
  const st = Number(to)
  const check = useQuery({
    queryKey: ['salary-check', candidate?.id, sf, st],
    queryFn: () => api.get<{ fit: string; message: string }>(`/api/employer/salary-check?candidate_id=${candidate?.id}&salary_from=${sf}&salary_to=${st}`),
    enabled: open && !!candidate && sf > 0 && st >= sf,
  })
  const m = useMutation({
    mutationFn: () =>
      api.post<Invitation>('/api/employer/invitations', {
        candidate_id: candidate?.id,
        search_id: searchId,
        title,
        description,
        salary_from: sf,
        salary_to: st,
        contact_method: method,
        contact_value: contact,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employer-invitations'] })
      onClose()
    },
  })
  return (
    <Modal open={open} onClose={onClose} title={`Приглашение: ${candidate?.label ?? ''}`}>
      {m.isSuccess ? null : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            m.mutate()
          }}
        >
          <Field label="Должность / суть предложения" required>
            <input className="input" required minLength={3} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Python-разработчик в команду платежей" />
          </Field>
          <Field label="Описание предложения" required hint="Чем займётся человек, команда, продукт, этапы найма">
            <textarea className="input min-h-28" required minLength={10} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Зарплата от, ₽" required>
              <input className="input" type="number" min={1} required value={from} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label="Зарплата до, ₽" required>
              <input className="input" type="number" min={1} required value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
          </div>
          {check.data && (
            <div className="flex items-center gap-2 text-sm">
              <SalaryFit fit={check.data.fit} />
              <span className="text-muted">{check.data.message}</span>
            </div>
          )}
          <div className="grid grid-cols-[9rem_1fr] gap-3">
            <Field label="Способ связи" required>
              <select className="input" value={method} onChange={(e) => setMethod(e.target.value)}>
                <option value="email">Email</option>
                <option value="telegram">Telegram</option>
                <option value="phone">Телефон</option>
                <option value="other">Другое</option>
              </select>
            </Field>
            <Field label="Контакт" required>
              <input className="input" required minLength={3} value={contact} onChange={(e) => setContact(e.target.value)} placeholder={method === 'telegram' ? '@hr_company' : 'hr@company.ru'} />
            </Field>
          </div>
          <Notice>Кандидат увидит компанию, предложение и вилку сразу. Его контакты откроются вам, когда он примет приглашение.</Notice>
          <ErrorBox error={m.error} />
          <button className="btn-primary w-full" disabled={m.isPending}>
            <Send className="h-4 w-4" /> Отправить приглашение
          </button>
        </form>
      )}
    </Modal>
  )
}
