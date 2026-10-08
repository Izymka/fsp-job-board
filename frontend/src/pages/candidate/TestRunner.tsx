import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, ArrowDown, ArrowUp, Ban, Camera, CheckCircle2, Clock, Flag, PartyPopper, RotateCcw, ShieldCheck, XCircle } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { SkillList } from '../../components/domain'
import { ProctorDock, Watermark } from '../../components/proctor'
import { Badge, CodeBlock, ErrorBox, Md, Notice, PageLoader, Progress, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { useMe } from '../../lib/auth'
import { detectEnv, enterFullscreen, exitFullscreen, isDesktop, useFullscreenGuard } from '../../lib/environment'
import { lookup, useCatalog } from '../../lib/catalog'
import { proctor, proctorWarning, useProctorLive } from '../../lib/proctor/session'
import type { Attempt, AttemptResult, GradeId, Item } from '../../lib/types'

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

const MIN_AWAY_MS = 1500 // короче — случайный клик мимо окна, не считаем

/** Сигналы надёжности по текущему заданию: уходы со страницы (вкладка или окно), копирование, вставка. */
function useIntegrity(itemKey: unknown) {
  const s = useRef({ losses: 0, away: 0, pastes: 0, copies: 0 })
  const awaySince = useRef<number | null>(null)
  const [lastAway, setLastAway] = useState<number | null>(null)
  useEffect(() => {
    s.current = { losses: 0, away: 0, pastes: 0, copies: 0 }
    setLastAway(null)
  }, [itemKey])
  useEffect(() => {
    const leave = () => {
      if (awaySince.current == null) awaySince.current = Date.now()
    }
    const back = () => {
      if (awaySince.current == null) return
      const d = Date.now() - awaySince.current
      awaySince.current = null
      if (d >= MIN_AWAY_MS) {
        s.current.losses += 1
        s.current.away += d
        setLastAway(d)
      }
    }
    const vis = () => (document.hidden ? leave() : back())
    document.addEventListener('visibilitychange', vis)
    window.addEventListener('blur', leave)
    window.addEventListener('focus', back)
    return () => {
      document.removeEventListener('visibilitychange', vis)
      window.removeEventListener('blur', leave)
      window.removeEventListener('focus', back)
    }
  }, [])
  const onCopy = useCallback((e: { preventDefault: () => void }) => {
    e.preventDefault()
    s.current.copies += 1
  }, [])
  const onPaste = useCallback((e: { preventDefault: () => void }) => {
    e.preventDefault()
    s.current.pastes += 1
  }, [])
  const snapshot = () => {
    // если ответ отправляется, пока окно не в фокусе, — досчитать текущий уход
    const extra = awaySince.current != null ? Date.now() - awaySince.current : 0
    return {
      tab_switches: s.current.losses + (extra >= MIN_AWAY_MS ? 1 : 0),
      away_ms: s.current.away + (extra >= MIN_AWAY_MS ? extra : 0),
      paste_attempts: s.current.pastes,
      copy_attempts: s.current.copies,
    }
  }
  return { onCopy, onPaste, snapshot, lastAway, flagged: s.current.losses > 0 && s.current.away >= 2000, dismiss: () => setLastAway(null) }
}

function ItemInput({ item, value, onChange, onPaste }: { item: Item; value: unknown; onChange: (v: unknown) => void; onPaste: (e: { preventDefault: () => void }) => void }) {
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
  if (item.kind === 'scenario' || item.kind === 'probe') {
    const text = (value as string) ?? ''
    return (
      <div>
        <textarea
          className={clsx('input font-sans leading-relaxed', item.kind === 'scenario' ? 'min-h-72' : 'min-h-36')}
          autoFocus
          value={text}
          onChange={(e) => onChange(e.target.value)}
          onPaste={onPaste}
          onDrop={(e) => e.preventDefault()}
          maxLength={6000}
          placeholder={item.kind === 'scenario' ? 'Опишите ход рассуждений, решение и как будете проверять результат. Конкретика важнее объёма.' : 'Коротко и по существу — 2–5 предложений.'}
          aria-label="Ответ"
        />
        <div className="mt-1 text-right text-xs text-muted">{text.length} / 6000</div>
      </div>
    )
  }
  return (
    <input
      className="input max-w-md font-mono"
      inputMode={item.kind === 'number' ? 'decimal' : 'text'}
      autoFocus
      value={(value as string) ?? ''}
      onChange={(e) => onChange(e.target.value)}
      onPaste={onPaste}
      onDrop={(e) => e.preventDefault()}
      placeholder={item.kind === 'number' ? 'Число' : 'Ваш ответ'}
      aria-label="Ответ"
    />
  )
}

const SCORE_TONE = ['bg-accent-50 text-accent-600', 'bg-warn-50 text-warn-600', 'bg-ok-50 text-ok-600', 'bg-brand-50 text-brand-700']

function ScenarioResult({ r }: { r: AttemptResult }) {
  const sc = r.scenario
  if (!sc) return null
  return (
    <Section title={`Практический кейс: ${sc.title}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={SCORE_TONE[sc.category]}>{sc.category_title}</Badge>
        <span className="text-xs text-muted">
          {sc.method === 'llm' ? 'оценено по рубрике' : 'предварительная автоматическая оценка по рубрике'} · тест знаний: {Math.round((r.knowledge_p_claimed ?? r.p_claimed) * 100)}% → с кейсом: {Math.round(r.p_claimed * 100)}%
        </span>
      </div>
      <ul className="mt-4 space-y-2.5">
        {sc.criteria.map((c) => (
          <li key={c.id} className="flex items-start gap-3 text-sm">
            <span className={clsx('mt-0.5 w-10 shrink-0 rounded-md py-0.5 text-center font-mono text-xs font-bold', SCORE_TONE[c.score])}>{c.score}/3</span>
            <span>
              <span className="font-medium">{c.title}</span>
              {c.evidence && <span className="block text-xs text-muted">«{c.evidence}»</span>}
            </span>
          </li>
        ))}
        {sc.probe && (
          <li className="flex items-start gap-3 text-sm">
            <span className={clsx('mt-0.5 w-10 shrink-0 rounded-md py-0.5 text-center font-mono text-xs font-bold', SCORE_TONE[sc.probe.score ?? 0])}>{sc.probe.score ?? 0}/3</span>
            <span>
              <span className="font-medium">Уточняющий вопрос</span>
              <span className="block text-xs text-muted">{sc.probe.question}</span>
            </span>
          </li>
        )}
      </ul>
      <p className="hint mt-3">0 — не раскрыто, 1 — в общих словах, 2 — на уровне грейда, 3 — сверх уровня. Кейс учитывается в общей оценке вместе с тестом знаний.</p>
    </Section>
  )
}

function ProctorNote({ r }: { r: AttemptResult }) {
  const pr = r.integrity?.proctoring
  if (!pr) return null
  if (pr.status === 'verified')
    return (
      <p className="flex items-center gap-1.5 text-xs text-ok-600">
        <ShieldCheck className="h-3.5 w-3.5" /> Тест пройден с цифровым проктором{pr.identity === 'enrolled' ? ' — эталон лица создан' : pr.identity === 'match' ? ', лицо совпало с эталоном профиля' : ''}.
      </p>
    )
  return <p className="text-xs text-muted">Проктор был прерван: камера или микрофон отключались дольше 30 секунд — отметка «Тест с проктором» не ставится.</p>
}

function IntegrityNote({ r }: { r: AttemptResult }) {
  const i = r.integrity
  if (!i) return null
  if (i.level === 'clean')
    return (
      <div className="space-y-1">
        <p className="flex items-center gap-1.5 text-xs text-ok-600">
          <ShieldCheck className="h-3.5 w-3.5" /> Замечаний к прохождению нет.
        </p>
        <ProctorNote r={r} />
      </div>
    )
  return (
    <div className="space-y-1">
      <Notice tone="warn">
        <b>Замечания к прохождению</b> (работодатель увидит их рядом с результатом): {i.reasons.join('; ')}.
      </Notice>
      <ProctorNote r={r} />
    </div>
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
    mutationFn: async (grade: GradeId) => {
      // предыдущая попытка шла с проктором и камера ещё открыта — следующая тоже с проктором
      const emb = a.proctored && proctor.opened ? await proctor.capture() : null
      const p = emb ? { proctored: true, embedding: emb, embedding_model: proctor.model } : {}
      return { x: await api.post<Attempt>('/api/assessment/attempts', { grade, ...p, env: detectEnv() }), emb }
    },
    onSuccess: ({ x, emb }) => {
      if (emb) proctor.start(emb)
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
            <button className="btn-primary" onClick={() => (void enterFullscreen(), start.mutate(next))} disabled={start.isPending}>
              <ArrowUp className="h-4 w-4" /> Пройти тест на {L.grade(next)}
            </button>
          )}
          {!ok && prev && (
            <button className="btn-primary" onClick={() => (void enterFullscreen(), start.mutate(prev))} disabled={start.isPending}>
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
      <IntegrityNote r={r} />
      <ScenarioResult r={r} />
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
  const attempt = useQuery({ queryKey: ['attempt', attemptId], queryFn: () => api.get<Attempt>(`/api/assessment/attempts/${attemptId}`) })
  const a = attempt.data
  const [value, setValue] = useState<unknown>(null)
  const t0 = useRef(Date.now())
  const item = a?.status === 'in_progress' ? a.item : null
  const left = useCountdown(item)
  const guard = useIntegrity(item)
  const live = useProctorLive()
  const me = useMe().data
  const fs = useFullscreenGuard(item, a?.status === 'in_progress' && isDesktop())
  const loadedAt = useRef(Date.now())
  const [resumeError, setResumeError] = useState<unknown>(null)
  useEffect(() => {
    setValue(item?.kind === 'order' ? item.options!.map((_, i) => i) : item?.kind === 'multi' ? [] : null)
    t0.current = Date.now()
    proctor.resetItem()
  }, [item])
  // экран результата: наблюдение на паузе (камера открыта для следующей попытки); уход со страницы — выключить
  useEffect(() => {
    if (a && a.status !== 'in_progress') {
      if (proctor.active) proctor.pause()
      exitFullscreen()
    }
  }, [a])
  useEffect(() => () => proctor.stop(), [])
  const resume = async () => {
    void enterFullscreen()
    setResumeError(null)
    try {
      await proctor.open()
      // время без камеры после перезагрузки страницы засчитывается как отключение камеры
      proctor.start(await proctor.capture(), Date.now() - loadedAt.current)
    } catch (e) {
      setResumeError(e)
    }
  }
  const answer = useMutation({
    mutationFn: (v: unknown) =>
      api.post<Attempt>(`/api/assessment/attempts/${attemptId}/answer`, {
        position: item!.position,
        value: v,
        time_ms: Date.now() - t0.current,
        ...guard.snapshot(),
        ...fs.snapshot(),
        ...(a?.proctored && proctor.active ? { proctor: proctor.counts(), embedding: proctor.embeddingForServer() } : {}),
      }),
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
  if (!a) return <PageLoader queries={[attempt]} />
  if (a.status === 'voided')
    return (
      <div className="mx-auto max-w-xl">
        <Section title="Попытка аннулирована">
          <div className="flex gap-3">
            <Ban className="mt-0.5 h-5 w-5 shrink-0 text-accent-600" />
            <div className="space-y-2 text-sm text-ink-soft">
              {(a.result?.explanation ?? []).map((x) => (
                <p key={x}>{x}</p>
              ))}
            </div>
          </div>
          <Link to="/candidate/test" className="btn-primary mt-4">
            К тестированию
          </Link>
        </Section>
      </div>
    )
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
  const isText = item.kind === 'scenario' || item.kind === 'probe'
  const canSubmit = value !== null && value !== '' && !(Array.isArray(value) && item.kind === 'multi' && value.length === 0) && !(isText && String(value).trim().length < 10)
  const lowTime = left != null && left <= (isText ? 60 : 15)
  const stages = a.has_scenario ? 2 : 1
  const stageTitle = item.stage === 'knowledge' ? 'Тест знаний' : item.stage === 'scenario' ? 'Практический кейс' : 'Уточняющий вопрос'
  const leavesLeft = Math.max(0, (a.integrity?.leaves_left ?? 3) - (guard.flagged ? 1 : 0))
  if (a.proctored && !live.active)
    return (
      <div className="mx-auto max-w-xl">
        <Section title="Тест идёт с цифровым проктором">
          <p className="text-sm text-ink-soft">Страница была перезагружена, и камера отключилась. Включите камеру и микрофон, чтобы продолжить. Время без камеры фиксируется: дольше 30 секунд — отметка «Тест с проктором» снимается, но попытка продолжается.</p>
          <ErrorBox error={resumeError} />
          <button className="btn-primary mt-4" onClick={() => void resume()}>
            <Camera className="h-4 w-4" /> Включить камеру и продолжить
          </button>
        </Section>
      </div>
    )
  if (!fs.full)
    return (
      <div className="mx-auto max-w-xl">
        <Section title="Тест идёт в полноэкранном режиме">
          <p className="text-sm text-ink-soft">Задание показывается только в полноэкранном режиме. Время вне него засчитывается как уход со страницы.</p>
          <button className="btn-primary mt-4" onClick={() => void enterFullscreen()}>
            Перейти в полноэкранный режим
          </button>
        </Section>
      </div>
    )
  const warning = fs.extended
    ? 'Подключён второй монитор. Отключите его — работодатель увидит замечание.'
    : fs.unavailable
      ? 'Браузер не разрешил полноэкранный режим. Тест можно продолжить, но работодатель увидит замечание — лучше откройте его в Chrome, Edge, Firefox или Safari.'
      : proctorWarning(live)
  const mark = `${a.id.slice(0, 8)} · ${(me?.id ?? '').slice(0, 6)}`
  return (
    <div className="mx-auto max-w-3xl">
      <ProctorDock />
      {warning && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-warn-600/30 bg-warn-50 px-4 py-3 text-sm text-warn-600" role="alert">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex-1">{warning}</div>
        </div>
      )}
      {guard.lastAway != null && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-accent-500/30 bg-accent-50 px-4 py-3 text-sm text-accent-600" role="alert">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex-1">
            Вы покинули страницу теста на {Math.round(guard.lastAway / 1000)} с — это зафиксировано.{' '}
            {leavesLeft > 0 ? `Ещё уходы на ${leavesLeft} заданиях — и попытка будет аннулирована.` : 'Следующий уход аннулирует попытку.'}
          </div>
          <button type="button" className="text-xs underline" onClick={guard.dismiss}>
            Понятно
          </button>
        </div>
      )}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {stages > 1 && (
            <Badge tone="bg-ink text-white">
              Этап {item.stage === 'knowledge' ? 1 : 2} из 2 · {stageTitle}
            </Badge>
          )}
          {item.stage === 'knowledge' && <Badge tone="bg-brand-50 text-brand-700">Задание {item.position + 1}</Badge>}
          <Badge tone="bg-surface text-ink-soft">{item.skill_title}</Badge>
        </div>
        <div className={clsx('flex items-center gap-1.5 font-mono text-sm', lowTime ? 'text-accent-600' : 'text-ink-soft')} aria-live="polite">
          <Clock className="h-4 w-4" />
          {left != null ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` : '—'}
        </div>
      </div>
      {item.stage === 'knowledge' ? (
        <>
          <Progress value={a.answered / a.max_items} />
          <p className="mt-1.5 text-xs text-muted">
            Отвечено {a.answered}. Тест адаптивный: он закончится, как только результат станет надёжным (от {a.min_items} до {a.max_items} заданий).
            {a.has_scenario && ' Затем — практический кейс.'}
          </p>
        </>
      ) : item.stage === 'scenario' ? (
        <Notice>
          Задача уровня вашего грейда, как в реальной работе. Важны ход мысли, конкретика и компромиссы, а не объём. После ответа будет уточняющий вопрос по вашему решению — на него 2 минуты.
        </Notice>
      ) : (
        <Notice tone="warn">Ответьте своими словами: вопрос задан по вашему решению. На ответ — 2 минуты.</Notice>
      )}
      <form
        className="card relative mt-5 overflow-hidden p-5 sm:p-7"
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit) answer.mutate(item.kind === 'number' ? String(value).replace(',', '.') : value)
        }}
      >
        <Watermark text={mark} />
        <div className="select-none" onCopy={guard.onCopy} onCut={guard.onCopy} onContextMenu={(e) => e.preventDefault()} onDragStart={(e) => e.preventDefault()}>
          <Md text={item.prompt} className="text-[15px]" />
          {item.code && <CodeBlock code={item.code} lang={item.code_lang} />}
          {item.task && <Md text={`**Задание.** ${item.task}`} className="mt-3 text-[15px]" />}
        </div>
        <div className="mt-5">
          <ItemInput item={item} value={value} onChange={setValue} onPaste={guard.onPaste} />
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
              <CheckCircle2 className="h-4 w-4" /> {answer.isPending && isText ? 'Оцениваем…' : 'Ответить'}
            </button>
          </div>
        </div>
      </form>
      <p className="mt-3 text-center text-xs text-muted">
        Копирование заданий и вставка текста в ответы отключены. Уход со страницы теста дольше 2 секунд фиксируется. Задание помечено кодом вашей попытки.
      </p>
    </div>
  )
}
