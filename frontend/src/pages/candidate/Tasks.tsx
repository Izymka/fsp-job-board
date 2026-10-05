import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { CalendarClock, CheckCircle2, ListChecks, XCircle } from 'lucide-react'
import { useState } from 'react'
import { Badge, CodeBlock, EmptyState, ErrorBox, Md, PageHeader, PageLoader, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { date } from '../../lib/catalog'
import type { Assignment } from '../../lib/types'

const ST: Record<string, { label: string; tone: string }> = {
  assigned: { label: 'Ждёт решения', tone: 'bg-brand-50 text-brand-700' },
  submitted: { label: 'Отправлено', tone: 'bg-warn-50 text-warn-600' },
  reviewed: { label: 'Оценено', tone: 'bg-ok-50 text-ok-600' },
  expired: { label: 'Просрочено', tone: 'bg-surface text-muted' },
}

function TaskCard({ a }: { a: Assignment }) {
  const qc = useQueryClient()
  const [value, setValue] = useState<unknown>(a.answer_kind === 'multi' ? [] : null)
  const [text, setText] = useState('')
  const submit = useMutation({
    mutationFn: () => api.post<Assignment>(`/api/candidate/tasks/${a.id}/submit`, a.kind === 'auto' ? { value } : { text }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  const open = a.status === 'assigned'
  return (
    <Section
      title={
        <span className="flex flex-wrap items-center gap-2">
          {a.title}
          <Badge tone={ST[a.status].tone}>{ST[a.status].label}</Badge>
        </span>
      }
      actions={<span className="text-xs text-muted">{a.company_name}</span>}
    >
      <Md text={a.prompt} />
      {a.code && <CodeBlock code={a.code} lang={a.code_lang} />}
      {open && a.kind === 'auto' && a.options && (
        <div className="mt-3 grid gap-2">
          {a.options.map((o, i) => (
            <label key={i} className={clsx('flex cursor-pointer gap-3 rounded-xl border px-4 py-2.5 text-sm', (a.answer_kind === 'multi' ? (value as number[]).includes(i) : value === i) ? 'border-brand-500 bg-brand-50' : 'border-line')}>
              <input
                type={a.answer_kind === 'multi' ? 'checkbox' : 'radio'}
                name={a.id}
                className="accent-brand-500"
                onChange={() => (a.answer_kind === 'multi' ? setValue((value as number[]).includes(i) ? (value as number[]).filter((x) => x !== i) : [...(value as number[]), i]) : setValue(i))}
              />
              <span className="font-mono text-[13px]">{o}</span>
            </label>
          ))}
        </div>
      )}
      {open && a.kind === 'auto' && !a.options && <input className="input mt-3 max-w-md font-mono" placeholder="Ответ" onChange={(e) => setValue(e.target.value)} />}
      {open && a.kind === 'open' && <textarea className="input mt-3 min-h-32" placeholder="Опишите подход к решению" value={text} onChange={(e) => setText(e.target.value)} />}
      {open && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button className="btn-primary" disabled={submit.isPending || (a.kind === 'open' ? text.length < 20 : value === null)} onClick={() => submit.mutate()}>
            Отправить решение
          </button>
          {a.due_at && (
            <span className="flex items-center gap-1 text-xs text-muted">
              <CalendarClock className="h-3.5 w-3.5" /> до {date(a.due_at)}
            </span>
          )}
        </div>
      )}
      <ErrorBox error={submit.error} />
      {a.status !== 'assigned' && a.kind === 'auto' && a.correct != null && (
        <p className={clsx('mt-3 flex items-center gap-1.5 text-sm', a.correct ? 'text-ok-600' : 'text-accent-600')}>
          {a.correct ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />} {a.correct ? 'Верно — навык подтверждается свежим результатом' : 'Неверно — попробуйте следующее задание'}
        </p>
      )}
      {a.status === 'reviewed' && (
        <p className="mt-3 text-sm">
          Оценка работодателя: <b>{Math.round((a.score ?? 0) * 100)}/100</b>
          {a.feedback && <span className="text-muted"> — {a.feedback}</span>}
        </p>
      )}
    </Section>
  )
}

export default function CandidateTasks() {
  const { data, isLoading } = useQuery({ queryKey: ['tasks'], queryFn: () => api.get<Assignment[]>('/api/candidate/tasks') })
  if (isLoading || !data) return <PageLoader />
  return (
    <div>
      <PageHeader
        eyebrow="Регулярные задания"
        title="Короткие задачи от работодателей"
        subtitle="Раз в две недели — задача по вашей специализации: решить или предложить подход. Свежие решения повышают актуальность профиля и подтверждают навыки."
      />
      {data.length === 0 ? (
        <EmptyState icon={<ListChecks className="h-6 w-6" />} title="Заданий пока нет" text="Задания назначаются после подтверждения грейда, если работодатели вашей специализации их публиковали." />
      ) : (
        <div className="space-y-4">
          {data.map((a) => (
            <TaskCard key={a.id} a={a} />
          ))}
        </div>
      )}
    </div>
  )
}
