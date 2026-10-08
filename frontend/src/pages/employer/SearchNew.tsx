import { useMutation } from '@tanstack/react-query'
import clsx from 'clsx'
import { Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BlueprintBars } from '../../components/domain'
import { TagInput } from '../../components/TagInput'
import { Badge, ErrorBox, Field, PageHeader, Section, Spinner } from '../../components/ui'
import { api } from '../../lib/api'
import { lookup, useCatalog } from '../../lib/catalog'
import type { GradeId, NeedParse, SearchOut } from '../../lib/types'

const EXAMPLE = `Ищем бэкенд-разработчика в команду платёжного шлюза (6 человек, Go и Python).
Задачи: микросервисы на Python (FastAPI), интеграции с банками по REST, оптимизация PostgreSQL, очереди на Kafka.
Обязательно: Python, PostgreSQL, Docker, опыт от 2 лет.
Будет плюсом: Kubernetes, gRPC.
Вилка 250–320 тыс. ₽, гибрид в Москве.`

export default function SearchNew() {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const nav = useNavigate()
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [spec, setSpec] = useState('')
  const [grade, setGrade] = useState<GradeId | ''>('')
  const [skills, setSkills] = useState<Record<string, number>>({})
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [format, setFormat] = useState('')
  const [years, setYears] = useState('')
  const [adjacent, setAdjacent] = useState(true)
  const [touched, setTouched] = useState<Record<string, boolean>>({})
  const parse = useMutation({ mutationFn: () => api.post<NeedParse>('/api/employer/needs/parse', { text, title }) })
  useEffect(() => {
    if (text.length < 25) return
    const t = setTimeout(() => parse.mutate(), 600)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, title])
  const p = parse.data
  useEffect(() => {
    if (!p) return
    if (!touched.spec && p.specialization) setSpec(p.specialization)
    if (!touched.grade && p.grade) setGrade(p.grade)
    if (!touched.skills) setSkills(p.skills)
    if (!touched.from && p.salary_from) setFrom(String(p.salary_from))
    if (!touched.to && p.salary_to) setTo(String(p.salary_to))
    if (!touched.format && p.work_format) setFormat(p.work_format)
    if (!touched.years && p.min_years != null) setYears(String(p.min_years))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p])
  const create = useMutation({
    mutationFn: () =>
      api.post<SearchOut>('/api/employer/searches', {
        title: title || `${L.spec(spec)} · ${L.grade(grade)}`,
        text,
        specialization: spec || null,
        grade: grade || null,
        skills,
        salary_from: from ? Number(from) : null,
        salary_to: to ? Number(to) : null,
        work_format: format || null,
        min_years: years === '' ? null : Number(years),
        include_adjacent: adjacent,
      }),
    onSuccess: (d) => nav(`/employer/searches/${d.search.id}`),
  })
  const techs = useMemo(() => (cat?.technologies ?? []).map((t) => t.name), [cat])
  const touch = (k: string) => setTouched((x) => ({ ...x, [k]: true }))
  return (
    <div>
      <PageHeader eyebrow="Новая подборка" title="Опишите, кого вы ищете" subtitle="Обычным текстом — как в вакансии или в письме коллеге. Система выделит стек, специализацию и грейд; всё можно поправить вручную." />
      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <Section>
          <div className="space-y-4">
            <Field label="Название подборки">
              <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Backend для платёжного шлюза" />
            </Field>
            <Field label="Какие специалисты нужны и чем занимается команда" required>
              <textarea className="input min-h-64" value={text} onChange={(e) => setText(e.target.value)} placeholder={EXAMPLE} />
            </Field>
            {!text && (
              <button className="btn-ghost btn-sm" onClick={() => setText(EXAMPLE)}>
                Вставить пример
              </button>
            )}
          </div>
        </Section>
        <div className="space-y-6">
          <Section
            title={
              <span className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-brand-500" /> Что мы поняли
              </span>
            }
            actions={parse.isPending ? <Spinner className="h-4 w-4" /> : null}
          >
            {!p && <p className="text-sm text-muted">Начните писать — разбор появится здесь.</p>}
            {p && (
              <div className="space-y-4">
                {p.explanation.length > 0 && (
                  <ul className="space-y-1 text-xs text-muted">
                    {p.explanation.map((e) => (
                      <li key={e}>• {e}</li>
                    ))}
                  </ul>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Специализация" required>
                    <select className="input" value={spec} onChange={(e) => (setSpec(e.target.value), touch('spec'))}>
                      <option value="">—</option>
                      {cat?.specializations.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.title}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Грейд" required>
                    <select className="input" value={grade} onChange={(e) => (setGrade(e.target.value as GradeId), touch('grade'))}>
                      <option value="">—</option>
                      {cat?.grades.map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <div>
                  <span className="label">Технологии · клик — обязательно / плюсом</span>
                  <div className="mb-2 flex flex-wrap gap-1.5">
                    {Object.entries(skills).map(([k, v]) => (
                      <span key={k} className={clsx('chip cursor-pointer', v >= 0.6 ? 'bg-ink text-white' : 'border border-line bg-white text-ink-soft')} onClick={() => (setSkills({ ...skills, [k]: v >= 0.6 ? 0.45 : 1 }), touch('skills'))}>
                        {k}
                        {v < 0.6 && ' · плюс'}
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            const n = { ...skills }
                            delete n[k]
                            setSkills(n)
                            touch('skills')
                          }}
                          aria-label={`Убрать ${k}`}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                  <TagInput value={[]} onChange={(v) => (setSkills({ ...skills, ...Object.fromEntries(v.map((x) => [x, 1])) }), touch('skills'))} suggestions={techs.filter((t) => !(t in skills))} placeholder="Добавить технологию" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Вилка от, ₽">
                    <input className="input" type="number" value={from} onChange={(e) => (setFrom(e.target.value), touch('from'))} />
                  </Field>
                  <Field label="до, ₽">
                    <input className="input" type="number" value={to} onChange={(e) => (setTo(e.target.value), touch('to'))} />
                  </Field>
                </div>
                <Field label="Опыт работы от, лет" hint="Учитывается релевантный опыт — в той же роли. Пусто — типичный для грейда">
                  <input className="input" type="number" min={0} max={20} step={0.5} value={years} onChange={(e) => (setYears(e.target.value), touch('years'))} />
                </Field>
                <Field label="Формат">
                  <select className="input" value={format} onChange={(e) => (setFormat(e.target.value), touch('format'))}>
                    <option value="">любой</option>
                    {cat?.work_formats.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.title}
                      </option>
                    ))}
                  </select>
                </Field>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={adjacent} onChange={(e) => setAdjacent(e.target.checked)} />
                  Показывать соседние грейды (с пометкой)
                </label>
              </div>
            )}
          </Section>
          {p && Object.keys(p.blueprint).length > 0 && (
            <Section title="Тест под эту вакансию проверил бы">
              <BlueprintBars blueprint={p.blueprint} label={L.skill} />
            </Section>
          )}
          <ErrorBox error={create.error} />
          <button className="btn-primary w-full py-3" disabled={!spec || !grade || create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? <Spinner className="h-4 w-4 text-white" /> : <Sparkles className="h-4 w-4" />} Показать подборку
          </button>
          {spec && grade && (
            <p className="text-center text-xs text-muted">
              Категория: <Badge tone="bg-brand-50 text-brand-700">{L.spec(spec)} · {L.grade(grade)}</Badge>
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
