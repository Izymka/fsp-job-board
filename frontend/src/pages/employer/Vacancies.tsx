import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Users } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Reasons, StatusBadge } from '../../components/domain'
import { Badge, EmptyState, ErrorBox, Field, Modal, PageHeader, PageLoader } from '../../components/ui'
import { api } from '../../lib/api'
import { APP_STATUS, date, lookup, range, useCatalog } from '../../lib/catalog'
import type { Application, GradeId, Vacancy } from '../../lib/types'

function VacancyForm({ v, onClose }: { v: Vacancy | null; onClose: () => void }) {
  const { data: cat } = useCatalog()
  const qc = useQueryClient()
  const [title, setTitle] = useState(v?.title ?? '')
  const [text, setText] = useState(v?.text ?? '')
  const [spec, setSpec] = useState(v?.specialization ?? '')
  const [grade, setGrade] = useState<GradeId | ''>(v?.grade ?? '')
  const [from, setFrom] = useState(v ? String(v.salary_from) : '')
  const [to, setTo] = useState(v ? String(v.salary_to) : '')
  const [fmt, setFmt] = useState(v?.work_format ?? '')
  const [city, setCity] = useState(v?.city ?? '')
  const [years, setYears] = useState(v?.min_years != null ? String(v.min_years) : '')
  const [fspFriendly, setFspFriendly] = useState(v?.fsp_friendly ?? false)
  const [status, setStatus] = useState(v?.status ?? 'published')
  const save = useMutation({
    mutationFn: () => {
      const body = { title, text, specialization: spec || null, grade: grade || null, salary_from: Number(from), salary_to: Number(to), work_format: fmt || null, city: city || null, min_years: years === '' ? null : Number(years), fsp_friendly: fspFriendly, status }
      return v ? api.put<Vacancy>(`/api/employer/vacancies/${v.id}`, body) : api.post<Vacancy>('/api/employer/vacancies', body)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employer-vacancies'] })
      onClose()
    },
  })
  return (
    <Modal open onClose={onClose} title={v ? 'Редактировать вакансию' : 'Новая вакансия'} wide>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <Field label="Название" required>
          <input className="input" required value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Текст вакансии" required hint="Стек, специализацию и грейд система определит из текста — или укажите явно ниже">
          <textarea className="input min-h-48" required minLength={20} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Специализация">
            <select className="input" value={spec} onChange={(e) => setSpec(e.target.value)}>
              <option value="">из текста</option>
              {cat?.specializations.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Грейд">
            <select className="input" value={grade} onChange={(e) => setGrade(e.target.value as GradeId)}>
              <option value="">из текста</option>
              {cat?.grades.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Зарплата от, ₽" required>
            <input className="input" type="number" min={1} required value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
          <Field label="до, ₽" required>
            <input className="input" type="number" min={1} required value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
          <Field label="Формат">
            <select className="input" value={fmt} onChange={(e) => setFmt(e.target.value)}>
              <option value="">из текста</option>
              {cat?.work_formats.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.title}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Город">
            <input className="input" value={city} onChange={(e) => setCity(e.target.value)} />
          </Field>
          <Field label="Опыт работы от, лет" hint="Пусто — из текста вакансии, 0 — можно без опыта">
            <input className="input" type="number" min={0} max={20} step={0.5} value={years} onChange={(e) => setYears(e.target.value)} />
          </Field>
        </div>
        <label className="flex items-start gap-2 rounded-xl border border-line p-3 text-sm">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-500" checked={fspFriendly} onChange={(e) => setFspFriendly(e.target.checked)} />
          <span>
            <b>Открыта для участников ФСП</b>
            <span className="block text-muted">Засчитываем подтверждённые реестром достижения ФСП как опыт работы — до требуемого стажа. Вакансия получит бейдж в ленте кандидатов, компания — бейдж «Партнёр ФСП».</span>
          </span>
        </label>
        <Field label="Статус">
          <select className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="published">Опубликована</option>
            <option value="draft">Черновик</option>
            <option value="closed">Закрыта</option>
          </select>
        </Field>
        <ErrorBox error={save.error} />
        <button className="btn-primary" disabled={save.isPending}>
          Сохранить
        </button>
      </form>
    </Modal>
  )
}

function ApplicationsModal({ v, onClose }: { v: Vacancy; onClose: () => void }) {
  const qc = useQueryClient()
  const apps = useQuery({ queryKey: ['applications', v.id], queryFn: () => api.get<Application[]>(`/api/employer/vacancies/${v.id}/applications`) })
  const data = apps.data
  const setStatus = useMutation({ mutationFn: (x: { id: string; status: string }) => api.post(`/api/employer/applications/${x.id}/status`, { status: x.status }), onSuccess: () => qc.invalidateQueries({ queryKey: ['applications', v.id] }) })
  return (
    <Modal open onClose={onClose} title={`Отклики: ${v.title}`} wide>
      {!data ? (
        <PageLoader queries={[apps]} />
      ) : data.length === 0 ? (
        <p className="text-sm text-muted">Откликов пока нет.</p>
      ) : (
        <div className="space-y-3">
          {data.map((a) => (
            <div key={a.id} className="rounded-xl border border-line p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <Link to={`/employer/candidates/${a.candidate?.id}`} className="font-mono font-bold hover:text-brand-600">
                    {a.candidate?.full_name ?? a.candidate?.alias}
                  </Link>
                  <div className="text-xs text-muted">
                    {a.candidate?.category} · {date(a.created_at)} · {Object.values(a.candidate?.contacts ?? {}).join(', ')}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {a.match && <span className="rounded-lg bg-brand-50 px-2 py-1 font-mono text-sm font-bold text-brand-600">{Math.round(a.match.score * 100)}</span>}
                  <StatusBadge status={a.status} map={APP_STATUS} />
                </div>
              </div>
              {a.cover_letter && <p className="mt-2 text-sm text-ink-soft">«{a.cover_letter}»</p>}
              {a.match && (
                <div className="mt-3">
                  <Reasons reasons={a.match.reasons.slice(0, 4)} compact />
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-1.5">
                {(['viewed', 'interview', 'rejected', 'hired'] as const).map((s) => (
                  <button key={s} className="btn-secondary btn-sm" disabled={a.status === s} onClick={() => setStatus.mutate({ id: a.id, status: s })}>
                    {APP_STATUS[s].label}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}

export default function EmployerVacancies() {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const [edit, setEdit] = useState<Vacancy | null | 'new'>(null)
  const [apps, setApps] = useState<Vacancy | null>(null)
  const vacs = useQuery({ queryKey: ['employer-vacancies'], queryFn: () => api.get<Vacancy[]>('/api/employer/vacancies') })
  const data = vacs.data
  if (!data) return <PageLoader queries={[vacs]} />
  return (
    <div>
      <PageHeader
        title="Вакансии и отклики"
        subtitle="Вилка обязательна."
        actions={
          <button className="btn-primary" onClick={() => setEdit('new')}>
            <Plus className="h-4 w-4" /> Новая вакансия
          </button>
        }
      />
      {data.length === 0 ? (
        <EmptyState title="Вакансий нет" text="Опубликуйте вакансию — или ищите кандидатов сами в подборке." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.map((v) => (
            <div key={v.id} className="card p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-mono font-bold">{v.title}</div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <Badge tone="bg-brand-50 text-brand-700">{v.category}</Badge>
                    <Badge>{v.status === 'published' ? 'опубликована' : v.status === 'draft' ? 'черновик' : 'закрыта'}</Badge>
                    {v.work_format && <Badge>{L.format(v.work_format)}</Badge>}
                    {v.fsp_friendly && <Badge tone="bg-ok-50 text-ok-600">открыта для ФСП</Badge>}
                  </div>
                </div>
                <button className="btn-ghost p-2" onClick={() => setEdit(v)} aria-label="Редактировать">
                  <Pencil className="h-4 w-4" />
                </button>
              </div>
              <div className="mt-3 font-mono text-lg font-bold text-brand-600">{range(v.salary_from, v.salary_to)}</div>
              <button className="btn-secondary mt-4 w-full" onClick={() => setApps(v)}>
                <Users className="h-4 w-4" /> Отклики ({v.applications ?? 0})
              </button>
            </div>
          ))}
        </div>
      )}
      {edit && <VacancyForm v={edit === 'new' ? null : edit} onClose={() => setEdit(null)} />}
      {apps && <ApplicationsModal v={apps} onClose={() => setApps(null)} />}
    </div>
  )
}
