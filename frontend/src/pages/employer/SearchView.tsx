import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { SlidersHorizontal, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { CandidateRow, InviteModal } from '../../components/domain'
import { Badge, EmptyState, PageHeader, PageLoader, Section, Tabs } from '../../components/ui'
import { api } from '../../lib/api'
import { lookup, money, pct, range, useCatalog } from '../../lib/catalog'
import type { Filters, GradeId, SearchOut } from '../../lib/types'

function FilterPanel({ s, onApply, pending }: { s: SearchOut; onApply: (f: Filters, note: string) => void; pending: boolean }) {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const [f, setF] = useState<Filters>(s.search.filters)
  useEffect(() => setF(s.search.filters), [s.search.filters])
  const gIdx = cat?.grades.findIndex((g) => g.id === s.search.grade) ?? 0
  const grades = (cat?.grades ?? []).filter((_, i) => Math.abs(i - gIdx) <= 1)
  const toggle = <T,>(arr: T[] | undefined, v: T) => ((arr ?? []).includes(v) ? (arr ?? []).filter((x) => x !== v) : [...(arr ?? []), v])
  const skillOpts = Object.keys(s.need.skills)
  const describe = (x: Filters) =>
    [
      x.grades?.length ? `грейд: ${x.grades.map(L.grade).join(', ')}` : null,
      x.skills?.length ? `стек: ${x.skills.join(', ')}` : null,
      x.has_fsp ? 'с ФСП' : null,
      x.formats?.length ? `формат: ${x.formats.map(L.format).join(', ')}` : null,
      x.only_active ? 'активно ищут' : null,
      x.salary_fit_only ? 'вилка подходит' : null,
      x.exclude_adjacent ? 'без соседних грейдов' : null,
    ]
      .filter(Boolean)
      .join('; ') || 'без фильтров'
  return (
    <div className="space-y-5 text-sm">
      <div>
        <div className="label">Грейд</div>
        <div className="flex flex-wrap gap-1.5">
          {grades.map((g) => (
            <button key={g.id} onClick={() => setF({ ...f, grades: toggle(f.grades, g.id as GradeId) })} className={clsx('chip border px-2.5 py-1', f.grades?.includes(g.id) ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink-soft')}>
              {g.name}
            </button>
          ))}
        </div>
      </div>
      <div>
        <div className="label">Обязательно в стеке</div>
        <div className="flex flex-wrap gap-1.5">
          {skillOpts.map((k) => (
            <button key={k} onClick={() => setF({ ...f, skills: toggle(f.skills, k) })} className={clsx('chip border px-2.5 py-1', f.skills?.includes(k) ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink-soft')}>
              {k}
            </button>
          ))}
        </div>
      </div>
      <div>
        <div className="label">Формат</div>
        <div className="flex flex-wrap gap-1.5">
          {cat?.work_formats.map((x) => (
            <button key={x.id} onClick={() => setF({ ...f, formats: toggle(f.formats, x.id) })} className={clsx('chip border px-2.5 py-1', f.formats?.includes(x.id) ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink-soft')}>
              {x.title}
            </button>
          ))}
        </div>
      </div>
      <div className="space-y-2">
        {[
          ['has_fsp', 'Есть подтверждённые достижения ФСП'],
          ['only_active', 'Только активно ищущие'],
          ['salary_fit_only', 'Вилка не ниже ожиданий'],
          ['exclude_adjacent', 'Без соседних грейдов'],
        ].map(([k, label]) => (
          <label key={k} className="flex items-center gap-2">
            <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={!!f[k as keyof Filters]} onChange={(e) => setF({ ...f, [k]: e.target.checked || undefined })} />
            {label}
          </label>
        ))}
      </div>
      <div className="flex gap-2">
        <button className="btn-primary flex-1" disabled={pending} onClick={() => onApply(f, describe(f))}>
          Применить
        </button>
        <button className="btn-secondary" disabled={pending} onClick={() => onApply({}, 'Сброс фильтров')}>
          Сбросить
        </button>
      </div>
    </div>
  )
}

export default function SearchView() {
  const { id } = useParams()
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const qc = useQueryClient()
  const key = ['search', id]
  const search = useQuery({ queryKey: key, queryFn: () => api.get<SearchOut>(`/api/employer/searches/${id}`) })
  const s = search.data
  const [tab, setTab] = useState<'all' | 'short'>('all')
  const [invite, setInvite] = useState<{ id: string; label: string } | null>(null)
  const [showFilters, setShowFilters] = useState(false)
  const apply = useMutation({ mutationFn: (v: { filters: Filters; note: string }) => api.put<SearchOut>(`/api/employer/searches/${id}/filters`, v), onSuccess: (d) => qc.setQueryData(key, d) })
  const pin = useMutation({
    mutationFn: (v: { cid: string; on: boolean }) => (v.on ? api.put(`/api/employer/searches/${id}/shortlist/${v.cid}`, {}) : api.del(`/api/employer/searches/${id}/shortlist/${v.cid}`)),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  })
  if (!s) return <PageLoader queries={[search]} />
  const rows = tab === 'short' ? s.results.filter((r) => r.shortlisted) : s.results
  const filtered = s.filtered_total !== s.base_total
  return (
    <div>
      <PageHeader
        title={s.search.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-1.5">
            <Badge tone="bg-brand-50 text-brand-700">{s.search.category}</Badge>
            <span className="ml-1">{range(s.need.salary_from, s.need.salary_to)}</span>
            {s.need.work_format && <span>· {L.format(s.need.work_format)}</span>}
            {s.need.min_years != null && <span>· {s.need.min_years ? `опыт от ${String(s.need.min_years).replace('.', ',')} г.` : 'можно без опыта'}</span>}
          </span>
        }
        actions={
          <button className="btn-secondary lg:hidden" onClick={() => setShowFilters(!showFilters)}>
            <SlidersHorizontal className="h-4 w-4" /> Фильтры
          </button>
        }
      />

      <div className="mb-6 flex flex-wrap gap-2">
        {s.categories.map((c) => (
          <span
            key={`${c.specialization}-${c.grade}`}
            title={`${c.with_fsp} с ФСП · медиана ожиданий ${money(c.salary_median)}${c.in_budget_share != null ? ` · ${pct(c.in_budget_share)} в вашей вилке` : ''}`}
            className={clsx('chip border px-3 py-1.5 text-sm', c.relation === 'target' ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink-soft')}
          >
            <span className="font-mono font-bold">{c.label}</span>
            <span className="ml-1.5 font-mono">{c.total}</span>
            {c.relation !== 'target' && <span className="ml-1.5 text-xs text-muted">{c.relation === 'adjacent' ? 'соседний грейд' : 'смежная'}</span>}
          </span>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[17rem_1fr]">
        <aside className={clsx('space-y-6', !showFilters && 'hidden lg:block')}>
          <Section title="Уточнить">
            <FilterPanel s={s} pending={apply.isPending} onApply={(filters, note) => apply.mutate({ filters, note })} />
          </Section>
        </aside>
        <div>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <Tabs
              value={tab}
              onChange={setTab}
              items={[
                { id: 'all', label: `Подборка (${s.filtered_total})` },
                { id: 'short', label: `Шорт-лист (${s.search.shortlist})` },
              ]}
            />
            {filtered && (
              <span className="flex items-center gap-2 text-xs text-muted">
                Показано {s.filtered_total} из {s.base_total}
                <button className="btn-ghost btn-sm" disabled={apply.isPending} onClick={() => apply.mutate({ filters: {}, note: 'Сброс уточнений' })}>
                  Сбросить уточнения
                </button>
              </span>
            )}
          </div>
          {rows.length === 0 ? (
            <EmptyState icon={<Users className="h-6 w-6" />} title={tab === 'short' ? 'Шорт-лист пуст' : 'Никого не нашлось'} text={tab === 'short' ? 'Закрепляйте кандидатов кнопкой с булавкой.' : 'Ослабьте фильтры или сбросьте уточнения.'} />
          ) : (
            <div className="space-y-3">
              {rows.map((r) => (
                <CandidateRow key={r.card.id} r={r} onInvite={() => setInvite({ id: r.card.id, label: r.card.alias })} onPin={() => pin.mutate({ cid: r.card.id, on: !r.shortlisted })} />
              ))}
            </div>
          )}
        </div>
      </div>
      {invite && (
        <InviteModal
          open
          candidate={invite}
          searchId={s.search.id}
          onClose={() => {
            setInvite(null)
            qc.invalidateQueries({ queryKey: key })
          }}
          defaults={{ title: s.search.title, salary_from: s.need.salary_from, salary_to: s.need.salary_to }}
        />
      )}
    </div>
  )
}
