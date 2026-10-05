import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, Send } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Reasons } from '../../components/domain'
import { Badge, EmptyState, ErrorBox, Field, Md, Modal, Notice, PageHeader, PageLoader } from '../../components/ui'
import { api } from '../../lib/api'
import { date, lookup, pct, range, useCatalog } from '../../lib/catalog'
import type { Application, Vacancy } from '../../lib/types'

function VacancyModal({ v, onClose }: { v: Vacancy; onClose: () => void }) {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const qc = useQueryClient()
  const [letter, setLetter] = useState('')
  const apply = useMutation({
    mutationFn: () => api.post<Application>(`/api/vacancies/${v.id}/apply`, { cover_letter: letter || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vacancies'] })
      qc.invalidateQueries({ queryKey: ['applications'] })
    },
  })
  return (
    <Modal open onClose={onClose} title={v.title} wide>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <b>{v.company_name}</b>
          <Badge tone="bg-brand-50 text-brand-700">{v.category}</Badge>
          {v.work_format && <Badge>{L.format(v.work_format)}</Badge>}
          {v.city && <span className="text-muted">{v.city}</span>}
        </div>
        <div className="font-mono text-2xl font-bold text-brand-600">{range(v.salary_from, v.salary_to)}</div>
        {v.match && (
          <div className="rounded-xl bg-surface p-4">
            <div className="mb-2 text-xs font-medium text-muted">Насколько вы подходите — {Math.round(v.match.score * 100)} / 100</div>
            <Reasons reasons={v.match.reasons} compact />
          </div>
        )}
        <Md text={v.text} />
        {v.company_stats && <p className="text-xs text-muted">Компания отвечает на {pct(v.company_stats.application_response_rate)} откликов.</p>}
        {v.applied || apply.isSuccess ? (
          <Notice tone="ok">
            Вы откликнулись. Статус — в разделе <Link to="/candidate/applications" className="link">«Мои отклики»</Link>.
          </Notice>
        ) : (
          <div className="space-y-3 border-t border-line pt-4">
            <Field label="Сопроводительное письмо (необязательно)">
              <textarea className="input min-h-20" value={letter} onChange={(e) => setLetter(e.target.value)} />
            </Field>
            <p className="text-xs text-muted">Откликаясь сами, вы открываете компании свои контакты.</p>
            <ErrorBox error={apply.error} />
            <button className="btn-primary" onClick={() => apply.mutate()} disabled={apply.isPending}>
              <Send className="h-4 w-4" /> Откликнуться
            </button>
          </div>
        )}
      </div>
    </Modal>
  )
}

export default function CandidateVacancies() {
  const [all, setAll] = useState(false)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<Vacancy | null>(null)
  const { data, isLoading } = useQuery({ queryKey: ['vacancies', all], queryFn: () => api.get<Vacancy[]>(`/api/vacancies?all_specializations=${all}`) })
  const rows = (data ?? []).filter((v) => !q || (v.title + v.company_name + v.text).toLowerCase().includes(q.toLowerCase()))
  return (
    <div>
      <PageHeader
        eyebrow="Классический сценарий"
        title="Вакансии"
        subtitle="Пока приглашений нет, можно проявить инициативу. Вакансии отсортированы по соответствию вашему подтверждённому профилю; зарплата указана в каждой."
        actions={
          <Link to="/candidate/applications" className="btn-secondary">
            Мои отклики
          </Link>
        }
      />
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute top-3 left-3 h-4 w-4 text-muted" />
          <input className="input pl-9" placeholder="Поиск по названию, компании, тексту" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={all} onChange={(e) => setAll(e.target.checked)} /> Все специализации
        </label>
      </div>
      {isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState title="Вакансий не найдено" text="Попробуйте включить все специализации или изменить запрос." />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {rows.map((v) => (
            <button key={v.id} onClick={() => setOpen(v)} className="card flex flex-col p-5 text-left transition-colors hover:border-brand-300">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-mono font-bold">{v.title}</div>
                  <div className="mt-0.5 text-sm text-muted">
                    {v.company_name} · {date(v.created_at)}
                  </div>
                </div>
                {v.match && <span className="rounded-lg bg-brand-50 px-2 py-1 font-mono text-sm font-bold text-brand-600">{Math.round(v.match.score * 100)}</span>}
              </div>
              <div className="mt-3 font-mono text-lg font-bold text-brand-600">{range(v.salary_from, v.salary_to)}</div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Badge tone="bg-brand-50 text-brand-700">{v.category}</Badge>
                {Object.keys(v.skills)
                  .slice(0, 5)
                  .map((s) => (
                    <Badge key={s}>{s}</Badge>
                  ))}
                {v.applied && <Badge tone="bg-ok-50 text-ok-600">отклик отправлен</Badge>}
              </div>
            </button>
          ))}
        </div>
      )}
      {open && <VacancyModal v={open} onClose={() => setOpen(null)} />}
    </div>
  )
}
