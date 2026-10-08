import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowRight, Plus } from 'lucide-react'
import { Link, Navigate } from 'react-router-dom'
import { EmptyState, PageHeader, PageLoader, Section, Stat } from '../../components/ui'
import { api } from '../../lib/api'
import { date, lookup, money, pct, useCatalog } from '../../lib/catalog'
import type { CategoryCell, Company, Insights, SearchSummary } from '../../lib/types'

export default function EmployerHome() {
  const catalog = useCatalog()
  const cat = catalog.data
  const L = lookup(cat)
  const company = useQuery({ queryKey: ['company'], queryFn: () => api.get<Company | null>('/api/employer/company') })
  const cells = useQuery({ queryKey: ['categories'], queryFn: () => api.get<CategoryCell[]>('/api/employer/categories'), enabled: !!company.data })
  const searches = useQuery({ queryKey: ['searches'], queryFn: () => api.get<SearchSummary[]>('/api/employer/searches'), enabled: !!company.data })
  const ins = useQuery({ queryKey: ['insights'], queryFn: () => api.get<Insights>('/api/employer/insights'), enabled: !!company.data })
  if (company.isLoading || company.isError) return <PageLoader queries={[company]} />
  if (!company.data) return <Navigate to="/employer/company" replace />
  if (!cat || !cells.data) return <PageLoader queries={[catalog, cells]} />
  const max = Math.max(1, ...cells.data.map((c) => c.total))
  const sent = Object.values(ins.data?.invitations ?? {}).reduce((a, b) => a + b, 0)
  return (
    <div>
      <PageHeader
        eyebrow={company.data.name}
        title="Найдите кандидата и пригласите сами"
        subtitle="Кандидаты распределены по категориям по результатам теста. Опишите потребность — получите подборку с объяснением, почему каждый кандидат в ней."
        actions={
          <Link to="/employer/searches/new" className="btn-primary">
            <Plus className="h-4 w-4" /> Новая подборка
          </Link>
        }
      />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Кандидатов в базе" value={cells.data.reduce((a, c) => a + c.total, 0)} hint={`${cells.data.reduce((a, c) => a + c.with_fsp, 0)} с достижениями ФСП`} />
        <Stat label="Приглашений отправлено" value={sent} />
        <Stat label="Принимают приглашения" value={pct(ins.data?.acceptance_rate)} />
        <Stat label="Медиана ответа" value={ins.data?.median_response_hours != null ? `${ins.data.median_response_hours} ч` : '—'} />
      </div>
      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <Section title="Категории кандидатов" actions={<span className="text-xs text-muted">клик — банк кандидатов категории</span>}>
          <div className="overflow-x-auto">
            <table className="w-full border-separate border-spacing-1 text-sm">
              <thead>
                <tr>
                  <th />
                  {cat.grades.map((g) => (
                    <th key={g.id} className="px-1 pb-1 text-center font-mono text-xs font-medium text-muted">
                      {g.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cat.specializations.map((s) => (
                  <tr key={s.id}>
                    <td className="pr-2 text-xs font-medium whitespace-nowrap text-ink-soft">{s.name}</td>
                    {cat.grades.map((g) => {
                      const c = cells.data.find((x) => x.specialization === s.id && x.grade === g.id)
                      const v = c?.total ?? 0
                      return (
                        <td key={g.id} className="p-0">
                          <Link
                            to={`/employer/candidates?specialization=${s.id}&grade=${g.id}`}
                            className={clsx('flex h-11 min-w-12 flex-col items-center justify-center rounded-lg font-mono text-sm transition-transform hover:scale-105', v === 0 ? 'bg-surface text-steel' : v / max > 0.5 ? 'bg-brand-500 text-white' : v / max > 0.2 ? 'bg-brand-200 text-brand-900' : 'bg-brand-50 text-brand-700')}
                            title={`${L.spec(s.id)} · ${L.grade(g.id)}: ${v} кандидатов, ${c?.with_fsp ?? 0} с ФСП`}
                          >
                            {v}
                            {c && c.with_fsp > 0 && <span className="text-[9px] leading-none opacity-80">ФСП {c.with_fsp}</span>}
                          </Link>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
        <div className="space-y-6">
          <Section title="Мои подборки" actions={<Link to="/employer/searches" className="link text-sm">Все</Link>}>
            {searches.data?.length ? (
              <ul className="divide-y divide-line">
                {searches.data.slice(0, 5).map((s) => (
                  <li key={s.id}>
                    <Link to={`/employer/searches/${s.id}`} className="flex items-center justify-between gap-3 py-2.5 hover:text-brand-600">
                      <div className="min-w-0">
                        <div className="truncate font-medium">{s.title}</div>
                        <div className="text-xs text-muted">
                          {s.category} · {date(s.updated_at)} · шорт-лист {s.shortlist}
                        </div>
                      </div>
                      <ArrowRight className="h-4 w-4 shrink-0 text-muted" />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="Подборок пока нет" text="Опишите, кого вы ищете, — система предложит категории и кандидатов." action={<Link to="/employer/searches/new" className="btn-primary">Описать потребность</Link>} />
            )}
          </Section>
          {ins.data && ins.data.decline_reasons.length > 0 && (
            <Section title="Почему отказываются">
              <ul className="space-y-2 text-sm">
                {ins.data.decline_reasons.map((r) => (
                  <li key={r.reason}>
                    <div className="flex justify-between">
                      <span>{r.title}</span>
                      <span className="font-mono text-muted">{pct(r.share)}</span>
                    </div>
                    <div className="mt-1 h-1.5 rounded-full bg-fog">
                      <div className="h-full rounded-full bg-accent-500" style={{ width: `${r.share * 100}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
              {ins.data.market.map((m) => (
                <p key={m.category} className="mt-3 text-xs text-muted">
                  {m.category}: медиана ожиданий {money(m.salary_median)} (25–75%: {money(m.salary_p25)} – {money(m.salary_p75)}), отказов по ЗП — {pct(m.declines_salary_share)}.
                </p>
              ))}
            </Section>
          )}
        </div>
      </div>
    </div>
  )
}
