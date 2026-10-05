import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CandidateMini, InviteModal } from '../../components/domain'
import { TagInput } from '../../components/TagInput'
import { EmptyState, PageHeader, PageLoader, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { useCatalog } from '../../lib/catalog'
import type { CandidateCard } from '../../lib/types'

interface Page {
  total: number
  page: number
  page_size: number
  items: CandidateCard[]
}

export default function EmployerBank() {
  const { data: cat } = useCatalog()
  const [params, setParams] = useSearchParams()
  const spec = params.get('specialization') ?? ''
  const grades = params.getAll('grade')
  const skills = params.getAll('skill')
  const confirmed = params.getAll('confirmed_skill')
  const hasFsp = params.get('has_fsp') ?? ''
  const fmt = params.getAll('work_format')
  const page = Number(params.get('page') ?? 1)
  const [invite, setInvite] = useState<{ id: string; label: string } | null>(null)
  const qs = params.toString()
  const { data, isLoading } = useQuery({ queryKey: ['bank', qs], queryFn: () => api.get<Page>(`/api/employer/candidates?${qs}`) })
  const update = (k: string, v: string | string[] | null) => {
    const n = new URLSearchParams(params)
    n.delete(k)
    n.delete('page')
    if (Array.isArray(v)) v.forEach((x) => n.append(k, x))
    else if (v) n.set(k, v)
    setParams(n)
  }
  const toggle = (k: string, arr: string[], v: string) => update(k, arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])
  return (
    <div>
      <PageHeader eyebrow="Банк кандидатов" title="Вся база по категориям" subtitle="Порядок — сила подтверждённого профиля внутри категории: результат теста, достижения ФСП, регулярные задания. Контакты скрыты до принятия приглашения." />
      <div className="grid gap-6 lg:grid-cols-[17rem_1fr]">
        <aside>
          <Section title="Фильтры">
            <div className="space-y-5 text-sm">
              <div>
                <div className="label">Специализация</div>
                <select className="input" value={spec} onChange={(e) => update('specialization', e.target.value || null)}>
                  <option value="">все</option>
                  {cat?.specializations.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className="label">Грейд</div>
                <div className="flex flex-wrap gap-1.5">
                  {cat?.grades.map((g) => (
                    <button key={g.id} onClick={() => toggle('grade', grades, g.id)} className={clsx('chip border px-2.5 py-1', grades.includes(g.id) ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink-soft')}>
                      {g.name}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="label">Стек</div>
                <TagInput value={skills} onChange={(v) => update('skill', v)} suggestions={(cat?.technologies ?? []).map((t) => t.name)} placeholder="Python, React…" />
              </div>
              <div>
                <div className="label">Подтверждено тестом</div>
                <div className="flex flex-wrap gap-1.5">
                  {(spec ? Object.keys(cat?.specializations.find((s) => s.id === spec)?.blueprint ?? {}) : ['python', 'sql', 'javascript', 'react', 'ml', 'testing']).map((k) => (
                    <button key={k} onClick={() => toggle('confirmed_skill', confirmed, k)} className={clsx('chip border px-2.5 py-1', confirmed.includes(k) ? 'border-ok-600 bg-ok-50 text-ok-600' : 'border-line text-ink-soft')}>
                      {cat?.assessment_skills.find((s) => s.id === k)?.title ?? k}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="label">Достижения ФСП</div>
                <select className="input" value={hasFsp} onChange={(e) => update('has_fsp', e.target.value || null)}>
                  <option value="">не важно</option>
                  <option value="true">есть</option>
                  <option value="false">нет</option>
                </select>
              </div>
              <div>
                <div className="label">Формат</div>
                <div className="flex flex-wrap gap-1.5">
                  {cat?.work_formats.map((x) => (
                    <button key={x.id} onClick={() => toggle('work_format', fmt, x.id)} className={clsx('chip border px-2.5 py-1', fmt.includes(x.id) ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink-soft')}>
                      {x.title}
                    </button>
                  ))}
                </div>
              </div>
              <button className="btn-ghost w-full" onClick={() => setParams(new URLSearchParams())}>
                Сбросить
              </button>
            </div>
          </Section>
        </aside>
        <div>
          {isLoading || !data ? (
            <PageLoader />
          ) : data.items.length === 0 ? (
            <EmptyState title="Никого не нашлось" text="Ослабьте фильтры." />
          ) : (
            <>
              <div className="mb-3 text-sm text-muted">Найдено: {data.total}</div>
              <div className="space-y-3">
                {data.items.map((c) => (
                  <CandidateMini
                    key={c.id}
                    c={c}
                    right={
                      <div className="flex shrink-0 items-center gap-3">
                        <div className="text-right">
                          <div className="text-[11px] text-muted">сила профиля</div>
                          <div className="font-mono text-lg font-bold text-brand-600">{Math.round(c.profile_strength * 100)}</div>
                        </div>
                        <button className="btn-primary btn-sm" onClick={() => setInvite({ id: c.id, label: c.alias })}>
                          Пригласить
                        </button>
                      </div>
                    }
                  />
                ))}
              </div>
              {data.total > data.page_size && (
                <div className="mt-5 flex items-center justify-center gap-2">
                  <button className="btn-secondary btn-sm" disabled={page <= 1} onClick={() => update('page', String(page - 1))}>
                    Назад
                  </button>
                  <span className="text-sm text-muted">
                    {page} / {Math.ceil(data.total / data.page_size)}
                  </span>
                  <button className="btn-secondary btn-sm" disabled={page * data.page_size >= data.total} onClick={() => update('page', String(page + 1))}>
                    Дальше
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      {invite && <InviteModal open candidate={invite} onClose={() => setInvite(null)} />}
    </div>
  )
}
