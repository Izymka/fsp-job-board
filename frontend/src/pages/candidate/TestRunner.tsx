import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowDown, ArrowUp, CheckCircle2, Clock, Flag, PartyPopper, RotateCcw, XCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { SkillList } from '../../components/domain'
import { Badge, CodeBlock, ErrorBox, Md, PageLoader, Progress, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { lookup, useCatalog } from '../../lib/catalog'
import type { Attempt, GradeId, Item } from '../../lib/types'

function useCountdown(item: Item | null) {
  const [left, setLeft] = useState<number | null>(null)
  useEffect(() => {
    if (!item) return
    const started = Date.now()
    setLeft(item.time_limit)
    const t = setInterval(() => setLeft(Math.max(0, item.time_limit - Math.floor((Date.now() - started) / 1000))), 500)
    return () => clearInterval(t)
  }, [item])
  return left
}

function ItemInput({ item, value, onChange }: { item: Item; value: unknown; onChange: (v: unknown) => void }) {
  if (item.kind === 'single')
    return (
      <div className="grid gap-2" role="radiogroup">
        {item.options!.map((o, i) => (
          <button
            key={i}
            type="button"
            role="radio"
            aria-checked={value === i}
            onClick={() => onChange(i)}
            className={clsx('flex items-start gap-3 rounded-xl border px-4 py-3 text-left text-sm transition-all', value === i ? 'border-brand-500 bg-brand-50 ring-2 ring-brand-100' : 'border-line hover:border-brand-300')}
          >
            <span className={clsx('mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2', value === i ? 'border-brand-500' : 'border-steel')}>
              {value === i && <span className="h-2.5 w-2.5 rounded-full bg-brand-500" />}
            </span>
            <span className="font-mono text-[13px] whitespace-pre-wrap">{o}</span>
          </button>
        ))}
      </div>
    )
  if (item.kind === 'multi') {
    const sel = (value as number[]) ?? []
    return (
      <div className="grid gap-2">
        {item.options!.map((o, i) => (
          <label key={i} className={clsx('flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 text-sm', sel.includes(i) ? 'border-brand-500 bg-brand-50' : 'border-line hover:border-brand-300')}>
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-500" checked={sel.includes(i)} onChange={() => onChange(sel.includes(i) ? sel.filter((x) => x !== i) : [...sel, i])} />
            <span className="font-mono text-[13px] whitespace-pre-wrap">{o}</span>
          </label>
        ))}
      </div>
    )
  }
  if (item.kind === 'order') {
    const order = (value as number[]) ?? item.options!.map((_, i) => i)
    const move = (k: number, d: number) => {
      const n = [...order]
      const j = k + d
      if (j < 0 || j >= n.length) return
      ;[n[k], n[j]] = [n[j], n[k]]
      onChange(n)
    }
    return (
      <ol className="grid gap-2">
        {order.map((idx, k) => (
          <li key={idx} className="flex items-center gap-3 rounded-xl border border-line bg-white px-3 py-2.5 text-sm">
            <span className="font-mono text-xs text-muted">{k + 1}</span>
            <span className="flex-1">{item.options![idx]}</span>
            <button type="button" className="btn-ghost p-1.5" onClick={() => move(k, -1)} disabled={k === 0} aria-label="Выше">
              <ArrowUp className="h-4 w-4" />
            </button>
            <button type="button" className="btn-ghost p-1.5" onClick={() => move(k, 1)} disabled={k === order.length - 1} aria-label="Ниже">
              <ArrowDown className="h-4 w-4" />
            </button>
          </li>
        ))}
      </ol>
    )
  }
  return (
    <input
      className="input max-w-md font-mono"
      inputMode={item.kind === 'number' ? 'decimal' : 'text'}
      autoFocus
      value={(value as string) ?? ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={item.kind === 'number' ? 'Число' : 'Ваш ответ'}
      aria-label="Ответ"
    />
  )
}

function Result({ a }: { a: Attempt }) {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const qc = useQueryClient()
  const nav = useNavigate()
  const r = a.result!
  const ok = r.decision === 'confirmed'
  const order = cat?.grades.map((g) => g.id) ?? []
  const next = order[order.indexOf(a.grade) + 1] as GradeId | undefined
  const prev = order[order.indexOf(a.grade) - 1] as GradeId | undefined
  const start = useMutation({
    mutationFn: (grade: GradeId) => api.post<Attempt>('/api/assessment/attempts', { grade }),
    onSuccess: (x) => {
      qc.invalidateQueries()
      nav(`/candidate/test/${x.id}`)
    },
  })
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <section className={clsx('card overflow-hidden p-6 sm:p-8', ok ? 'border-ok-600/30' : 'border-warn-600/30')}>
        <div className="flex items-start gap-4">
          <div className={clsx('flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl', ok ? 'bg-ok-50 text-ok-600' : 'bg-warn-50 text-warn-600')}>
            {ok ? <PartyPopper className="h-6 w-6" /> : <Flag className="h-6 w-6" />}
          </div>
          <div>
            <div className="text-xs tracking-wider text-muted uppercase">Результат теста · {r.n_items} заданий</div>
            <h1 className="mt-1 text-2xl font-bold sm:text-3xl">{ok ? `Грейд ${L.grade(a.grade)} подтверждён` : `${L.grade(a.grade)} пока не подтверждён`}</h1>
            <p className="mt-1 text-sm text-muted">{ok ? `Ваша категория: ${L.spec(a.specialization)} · ${L.grade(a.grade)}. Работодатели уже могут вас найти.` : 'Грейд не понижается. Выберите, как продолжить.'}</p>
          </div>
        </div>
        <ul className="mt-5 space-y-1.5 text-sm text-ink-soft">
          {r.explanation.map((x) => (
            <li key={x}>• {x}</li>
          ))}
        </ul>
        <div className="mt-6 flex flex-wrap gap-2">
          {ok && r.suggestion === 'upgrade' && next && (
            <button className="btn-primary" onClick={() => start.mutate(next)} disabled={start.isPending}>
              <ArrowUp className="h-4 w-4" /> Пройти тест на {L.grade(next)}
            </button>
          )}
          {!ok && prev && (
            <button className="btn-primary" onClick={() => start.mutate(prev)} disabled={start.isPending}>
              <RotateCcw className="h-4 w-4" /> Пройти тест на {L.grade(prev)}
            </button>
          )}
          <Link to="/candidate" className="btn-secondary">
            В кабинет
          </Link>
        </div>
        <div className="mt-3">
          <ErrorBox error={start.error} />
        </div>
      </section>
      <Section title="Подоценки навыков">
        <SkillList scores={Object.fromEntries(Object.entries(r.skills).map(([k, v]) => [k, { ...v, title: '' }]))} />
        <p className="hint mt-3">Подтверждение навыка учитывает и общий уровень: при малом числе заданий оценка навыка осторожно «сжимается» к общей — так статус не скачет от случайностей.</p>
      </Section>
    </div>
  )
}

export default function TestRunner() {
  const { attemptId } = useParams()
  const qc = useQueryClient()
  const nav = useNavigate()
  const { data: a, error } = useQuery({ queryKey: ['attempt', attemptId], queryFn: () => api.get<Attempt>(`/api/assessment/attempts/${attemptId}`) })
  const [value, setValue] = useState<unknown>(null)
  const switches = useRef(0)
  const t0 = useRef(Date.now())
  const item = a?.status === 'in_progress' ? a.item : null
  const left = useCountdown(item)
  useEffect(() => {
    setValue(item?.kind === 'order' ? item.options!.map((_, i) => i) : item?.kind === 'multi' ? [] : null)
    switches.current = 0
    t0.current = Date.now()
  }, [item])
  useEffect(() => {
    const h = () => {
      if (document.hidden) switches.current += 1
    }
    document.addEventListener('visibilitychange', h)
    return () => document.removeEventListener('visibilitychange', h)
  }, [])
  const answer = useMutation({
    mutationFn: (v: unknown) => api.post<Attempt>(`/api/assessment/attempts/${attemptId}/answer`, { position: item!.position, value: v, time_ms: Date.now() - t0.current, tab_switches: switches.current }),
    onSuccess: (d) => {
      qc.setQueryData(['attempt', attemptId], d)
      if (d.status !== 'in_progress') {
        qc.invalidateQueries({ queryKey: ['profile'] })
        qc.invalidateQueries({ queryKey: ['eligibility'] })
        qc.invalidateQueries({ queryKey: ['attempts'] })
        qc.invalidateQueries({ queryKey: ['dashboard'] })
        qc.invalidateQueries({ queryKey: ['me'] })
      }
    },
  })
  const abandon = useMutation({
    mutationFn: () => api.post<Attempt>(`/api/assessment/attempts/${attemptId}/abandon`),
    onSuccess: () => {
      qc.invalidateQueries()
      nav('/candidate/test')
    },
  })
  useEffect(() => {
    if (left === 0 && item && !answer.isPending) answer.mutate(value)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [left])
  if (error) return <ErrorBox error={error} />
  if (!a) return <PageLoader />
  if (a.status !== 'in_progress') {
    if (a.result) return <Result a={a} />
    return (
      <div className="mx-auto max-w-xl">
        <Section title="Попытка прервана">
          <p className="text-sm text-muted">Брошенная попытка засчитывается как неудачная. Вернитесь к выбору уровня.</p>
          <Link to="/candidate/test" className="btn-primary mt-4">
            К тестированию
          </Link>
        </Section>
      </div>
    )
  }
  if (!item) return <PageLoader />
  const canSubmit = value !== null && value !== '' && !(Array.isArray(value) && item.kind === 'multi' && value.length === 0)
  const lowTime = left != null && left <= 15
  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Badge tone="bg-brand-50 text-brand-700">Задание {item.position + 1}</Badge>
          <Badge tone="bg-surface text-ink-soft">{item.skill_title}</Badge>
        </div>
        <div className={clsx('flex items-center gap-1.5 font-mono text-sm', lowTime ? 'text-accent-600' : 'text-ink-soft')} aria-live="polite">
          <Clock className="h-4 w-4" />
          {left != null ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` : '—'}
        </div>
      </div>
      <Progress value={a.answered / a.max_items} />
      <p className="mt-1.5 text-xs text-muted">
        Отвечено {a.answered}. Тест адаптивный: он закончится, как только результат станет надёжным (от {a.min_items} до {a.max_items} заданий).
      </p>
      <form
        className="card mt-5 p-5 sm:p-7"
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit) answer.mutate(item.kind === 'number' ? String(value).replace(',', '.') : value)
        }}
      >
        <Md text={item.prompt} className="text-[15px]" />
        {item.code && <CodeBlock code={item.code} lang={item.code_lang} />}
        <div className="mt-5">
          <ItemInput item={item} value={value} onChange={setValue} />
        </div>
        <ErrorBox error={answer.error} />
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <button type="button" className="btn-ghost text-xs" onClick={() => window.confirm('Прервать попытку? Она будет засчитана как неудачная.') && abandon.mutate()}>
            <XCircle className="h-4 w-4" /> Прервать тест
          </button>
          <div className="flex gap-2">
            <button type="button" className="btn-secondary" disabled={answer.isPending} onClick={() => answer.mutate(null)} title="Пропуск засчитывается как неверный ответ">
              Не знаю
            </button>
            <button className="btn-primary px-6" disabled={!canSubmit || answer.isPending}>
              <CheckCircle2 className="h-4 w-4" /> Ответить
            </button>
          </div>
        </div>
      </form>
      <p className="mt-3 text-center text-xs text-muted">Правильные ответы не показываются во время теста — у каждого кандидата свои варианты заданий.</p>
    </div>
  )
}
