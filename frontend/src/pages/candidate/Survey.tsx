import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { TagInput } from '../../components/TagInput'
import { ErrorBox, Field, Notice, PageHeader, PageLoader, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { lookup, useCatalog } from '../../lib/catalog'
import type { GradeId, Profile } from '../../lib/types'

export default function CandidateSurvey() {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const qc = useQueryClient()
  const nav = useNavigate()
  const { data: p } = useQuery({ queryKey: ['profile'], queryFn: () => api.get<Profile>('/api/candidate/profile') })
  const hint = (p?.resume_parsed ?? {}) as { specialization_hint?: string; grade_hint?: GradeId; grade_reason?: string; skills?: string[] }
  const [industries, setIndustries] = useState<string[]>([])
  const [spec, setSpec] = useState('')
  const [stack, setStack] = useState<string[]>([])
  const [formats, setFormats] = useState<string[]>(['remote'])
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [status, setStatus] = useState('active')
  const [grade, setGrade] = useState<GradeId | ''>('')
  useEffect(() => {
    if (!p) return
    setIndustries(p.industries)
    setSpec(p.specialization ?? hint.specialization_hint ?? '')
    setStack(p.stack.length ? p.stack : (hint.skills ?? []).slice(0, 15))
    if (p.work_formats.length) setFormats(p.work_formats)
    setFrom(p.salary_from ? String(p.salary_from) : '')
    setTo(p.salary_to ? String(p.salary_to) : '')
    setStatus(p.search_status)
    setGrade(p.claimed_grade ?? hint.grade_hint ?? '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p])
  const techSuggestions = useMemo(() => {
    const all = cat?.technologies ?? []
    return [...all].sort((a, b) => (b.specializations[spec] ?? 0) - (a.specializations[spec] ?? 0)).map((t) => t.name)
  }, [cat, spec])
  const m = useMutation({
    mutationFn: () =>
      api.put<Profile>('/api/candidate/survey', {
        industries,
        specialization: spec,
        stack,
        work_formats: formats,
        salary_from: Number(from),
        salary_to: to ? Number(to) : null,
        search_status: status,
        claimed_grade: grade,
      }),
    onSuccess: (data) => {
      qc.setQueryData(['profile'], data)
      qc.invalidateQueries({ queryKey: ['me'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      nav(data.confirmed_grade ? '/candidate' : '/candidate/test')
    },
  })
  if (!cat || !p) return <PageLoader />
  const toggle = (arr: string[], v: string, set: (x: string[]) => void) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])
  const specChanged = p.confirmed_grade && p.specialization && spec !== p.specialization
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        eyebrow="Шаг 2 из 3 · Опрос"
        title="Специализация, стек и ожидания"
        subtitle="Специализация и заявленный грейд определяют содержание теста. Стек и ожидания используются в подборе. Резюме лишь подсказывает — категорию определит тест."
      />
      <form
        className="space-y-6"
        onSubmit={(e) => {
          e.preventDefault()
          m.mutate()
        }}
      >
        <Section title="Специализация">
          <div className="grid gap-2 sm:grid-cols-2">
            {cat.specializations.map((s) => (
              <button
                type="button"
                key={s.id}
                onClick={() => setSpec(s.id)}
                className={clsx('rounded-xl border p-3 text-left transition-all', spec === s.id ? 'border-brand-500 bg-brand-50 ring-2 ring-brand-100' : 'border-line hover:border-brand-300')}
              >
                <div className="font-medium">{s.title}</div>
                <div className="mt-0.5 text-xs text-muted">{s.description}</div>
              </button>
            ))}
          </div>
          {hint.specialization_hint && !p.specialization && <p className="hint mt-2">Подсказка из резюме: {L.specTitle(hint.specialization_hint)}</p>}
          {specChanged && (
            <div className="mt-3">
              <Notice tone="warn">Смена специализации — это новая категория: текущий подтверждённый грейд будет сброшен, понадобится пройти тест заново.</Notice>
            </div>
          )}
        </Section>

        <Section title="Отрасль">
          <p className="mb-3 text-sm text-muted">В каких отраслях вам интересно работать (до 6).</p>
          <div className="flex flex-wrap gap-2">
            {cat.industries.map((i) => (
              <button
                type="button"
                key={i.id}
                onClick={() => toggle(industries, i.id, setIndustries)}
                className={clsx('chip border px-3 py-1.5 text-sm', industries.includes(i.id) ? 'border-brand-500 bg-brand-500 text-white' : 'border-line bg-white text-ink-soft hover:border-brand-300')}
              >
                {i.title}
              </button>
            ))}
          </div>
        </Section>

        <Section title="Стек">
          <TagInput value={stack} onChange={setStack} suggestions={techSuggestions} placeholder="Python, PostgreSQL, Docker…" />
          <p className="hint">Заявленные технологии видны работодателю как «заявлено». Подтверждёнными их сделает тест и регулярные задания.</p>
        </Section>

        <Section title="Грейд, на который вы претендуете">
          <div className="grid gap-2 sm:grid-cols-5">
            {cat.grades.map((g) => (
              <button
                type="button"
                key={g.id}
                onClick={() => setGrade(g.id)}
                className={clsx('rounded-xl border p-3 text-left', grade === g.id ? 'border-brand-500 bg-brand-50 ring-2 ring-brand-100' : 'border-line hover:border-brand-300')}
              >
                <div className="font-mono font-bold">{g.name}</div>
                <div className="mt-0.5 text-[11px] leading-tight text-muted">{g.experience}</div>
              </button>
            ))}
          </div>
          {hint.grade_hint && <p className="hint mt-2">Подсказка из резюме: {L.grade(hint.grade_hint)} ({hint.grade_reason}).</p>}
          <p className="hint">Тест проверит именно этот уровень. Если не подтвердится — грейд не понизят: можно сразу пройти тест на уровень ниже.</p>
        </Section>

        <Section title="Условия">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Ожидания по зарплате от, ₽ (на руки)" required>
              <input className="input" type="number" min={1} required value={from} onChange={(e) => setFrom(e.target.value)} placeholder="200000" />
            </Field>
            <Field label="до, ₽" hint="Необязательно">
              <input className="input" type="number" min={1} value={to} onChange={(e) => setTo(e.target.value)} placeholder="260000" />
            </Field>
          </div>
          <div className="mt-4">
            <span className="label">Формат работы</span>
            <div className="flex flex-wrap gap-2">
              {cat.work_formats.map((f) => (
                <label key={f.id} className={clsx('chip cursor-pointer border px-3 py-1.5 text-sm', formats.includes(f.id) ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink-soft')}>
                  <input type="checkbox" className="sr-only" checked={formats.includes(f.id)} onChange={() => toggle(formats, f.id, setFormats)} />
                  {f.title}
                </label>
              ))}
            </div>
          </div>
          <div className="mt-4">
            <span className="label">Статус поиска</span>
            <div className="flex flex-wrap gap-2">
              {cat.search_statuses.map((s) => (
                <label key={s.id} className={clsx('chip cursor-pointer border px-3 py-1.5 text-sm', status === s.id ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink-soft')}>
                  <input type="radio" className="sr-only" name="status" checked={status === s.id} onChange={() => setStatus(s.id)} />
                  {s.title}
                </label>
              ))}
            </div>
            <p className="hint">«Не ищу» — профиль не показывается работодателям.</p>
          </div>
        </Section>

        <ErrorBox error={m.error} />
        <div className="flex gap-3">
          <button className="btn-primary px-6" disabled={!spec || !grade || !from || !formats.length || m.isPending}>
            Сохранить и перейти к тесту
          </button>
        </div>
      </form>
    </div>
  )
}
