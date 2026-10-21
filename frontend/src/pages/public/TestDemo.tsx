import { useMutation, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronDown, Wand2 } from 'lucide-react'
import { useState } from 'react'
import { BlueprintBars } from '../../components/domain'
import { Badge, CodeBlock, ErrorBox, Md, More, PageHeader, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { useAuth, useMe } from '../../lib/auth'
import { lookup, useCatalog } from '../../lib/catalog'
import type { GradeId, PreviewOut } from '../../lib/types'

interface DemoVacancy {
  id: string
  company: string
  title: string
  text: string
}

const LEVEL = ['', 'базовый', 'начальный', 'средний', 'продвинутый', 'экспертный']

export default function TestDemo() {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  // превью отдаёт формулировки заданий из банка — генерация доступна только работодателю
  const { ready, authenticated, login } = useAuth()
  const me = useMe()
  const canRun = me.data?.role === 'employer'
  const { data: demos } = useQuery({ queryKey: ['demo-vacancies'], queryFn: () => api.get<DemoVacancy[]>('/api/catalog/demo-vacancies'), staleTime: Infinity })
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [grade, setGrade] = useState<GradeId | ''>('')
  const [open, setOpen] = useState<string | null>(null)
  const m = useMutation({
    mutationFn: () => api.post<PreviewOut>('/api/assessment/preview', { text, title, grade: grade || null, candidates: 2, items: 8 }),
  })
  const pick = (v: DemoVacancy) => {
    setTitle(v.title)
    setText(v.text)
    m.reset()
  }
  const d = m.data
  return (
    <div>
      <PageHeader
        eyebrow="Механика тестирования"
        title="Как тест формируется из описания вакансии"
        subtitle="Иллюстрация: из текста вакансии выделяются навыки, по ним строится состав теста. Два кандидата одинаковой силы получают разные задания сопоставимой сложности. Тест кандидата собирается так же — из ядра специализации и модулей его стека."
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_1.3fr]">
        <Section title="Описание вакансии">
          <div className="mb-3 flex flex-wrap gap-2">
            {demos?.map((v) => (
              <button key={v.id} className={clsx('btn-secondary btn-sm', title === v.title && 'border-brand-500 bg-brand-50')} onClick={() => pick(v)}>
                {v.title}
              </button>
            ))}
          </div>
          <input className="input mb-3" placeholder="Заголовок вакансии" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea className="input min-h-64 font-mono text-xs" placeholder="Вставьте текст вакансии или выберите пример выше" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <select className="input w-auto" value={grade} onChange={(e) => setGrade(e.target.value as GradeId)}>
              <option value="">Грейд — из текста</option>
              {cat?.grades.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            {canRun ? (
              <button className="btn-primary" disabled={text.length < 20 || m.isPending} onClick={() => m.mutate()}>
                <Wand2 className="h-4 w-4" /> Сформировать тест
              </button>
            ) : ready && !authenticated ? (
              <button className="btn-primary" onClick={() => login('/test-demo')}>
                <Wand2 className="h-4 w-4" /> Войти как работодатель
              </button>
            ) : null}
          </div>
          <div className="mt-3">
            <ErrorBox error={m.error} />
          </div>
        </Section>

        <div className="space-y-6">
          {!d && (
            <div className="card flex min-h-64 items-center justify-center p-8 text-center text-sm text-muted">
              {canRun
                ? 'Выберите пример вакансии или вставьте свою — и нажмите «Сформировать тест».'
                : me.data?.role
                  ? 'Генерация теста по вакансии доступна в кабинете работодателя: она показывает формулировки заданий из банка теста.'
                  : 'Генерация теста по вакансии доступна работодателям — войдите, чтобы попробовать на своём тексте или на примере.'}
            </div>
          )}
          {d && (
            <>
              <Section title="1. Разбор вакансии">
                <div className="flex flex-wrap gap-2 text-sm">
                  <Badge tone="bg-brand-50 text-brand-700">{L.specTitle(d.specialization)}</Badge>
                  <Badge tone="bg-brand-50 text-brand-700">Грейд {L.grade(d.grade)}</Badge>
                </div>
                <ul className="mt-3 space-y-1 text-sm text-muted">
                  {d.explanation.map((e) => (
                    <li key={e}>• {e}</li>
                  ))}
                </ul>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {Object.entries(d.parsed_skills).map(([k, v]) => (
                    <Badge key={k} tone={v >= 0.6 ? 'bg-ink text-white' : 'bg-surface text-ink-soft'}>
                      {k}
                      {v < 0.6 && ' · плюс'}
                    </Badge>
                  ))}
                </div>
              </Section>
              <Section title="2. Blueprint теста — доли навыков">
                <BlueprintBars blueprint={d.blueprint} label={L.skill} />
              </Section>
            </>
          )}
        </div>
      </div>

      {d && (
        <div className="mt-6">
          <h2 className="mb-1 text-xl font-bold">3. Два кандидата — два разных теста</h2>
          <p className="mb-2 text-sm text-muted">
            Совпавших формулировок: <b className="text-ink">{d.shared_instances}</b> из {d.tests[0]?.items.length ?? 0}, общих семейств: {d.shared_families}.
          </p>
          <More label="Технические детали" className="mb-4">
            <p className="text-sm text-muted">
              Средняя сложность (b): {d.tests.map((t) => `${t.label} — ${t.mean_b.toFixed(2)}`).join(', ')}. Информативность в точке порога грейда: {d.tests.map((t) => t.total_information.toFixed(1)).join(' и ')}.
              {d.shared_instances > 0 && ' Совпадают концептуальные вопросы с выбором: формулировок у них немного, варианты ответов перемешаны, а их доля в банке ограничена.'}
            </p>
          </More>
          <div className="grid gap-6 lg:grid-cols-2">
            {d.tests.map((t) => (
              <Section key={t.label} title={t.label} actions={<span className="text-xs text-muted">{Object.entries(t.skill_mix).map(([k, n]) => `${L.skill(k)} ×${n}`).join(' · ')}</span>}>
                <ol className="space-y-2">
                  {t.items.map((it, i) => {
                    const key = `${t.label}-${i}`
                    return (
                      <li key={key} className="rounded-xl border border-line">
                        <button className="flex w-full items-center gap-3 px-3 py-2.5 text-left" onClick={() => setOpen(open === key ? null : key)}>
                          <span className="font-mono text-xs text-muted">{String(i + 1).padStart(2, '0')}</span>
                          <span className="flex-1 text-sm">
                            <span className="font-medium">{it.family_title}</span>
                            <span className="block text-xs text-muted">
                              {it.skill_title} · уровень {it.level} ({LEVEL[it.level]})
                            </span>
                          </span>
                          <ChevronDown className={clsx('h-4 w-4 text-muted transition-transform', open === key && 'rotate-180')} />
                        </button>
                        {open === key && (
                          <div className="border-t border-line px-3 py-2">
                            <Md text={it.prompt} />
                            {it.code && <CodeBlock code={it.code} lang={it.code_lang} />}
                            {it.options && (
                              <ul className="mt-2 space-y-1 text-sm">
                                {it.options.map((o) => (
                                  <li key={o} className="rounded-lg bg-surface px-3 py-1.5">
                                    {o}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ol>
              </Section>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
