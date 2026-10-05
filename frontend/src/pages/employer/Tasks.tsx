import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { Badge, EmptyState, ErrorBox, Field, Modal, PageHeader, PageLoader } from '../../components/ui'
import { api } from '../../lib/api'
import { date, lookup, useCatalog } from '../../lib/catalog'
import type { Assignment, TaskOut } from '../../lib/types'

function NewTask({ onClose }: { onClose: () => void }) {
  const { data: cat } = useCatalog()
  const qc = useQueryClient()
  const [kind, setKind] = useState<'auto' | 'open'>('auto')
  const [title, setTitle] = useState('')
  const [spec, setSpec] = useState('backend')
  const [skill, setSkill] = useState('sql')
  const [prompt, setPrompt] = useState('')
  const [rubric, setRubric] = useState('')
  const m = useMutation({
    mutationFn: () => api.post<TaskOut>('/api/employer/tasks', { title, kind, specialization: spec, skill: kind === 'auto' ? skill : null, prompt: kind === 'open' ? prompt : null, rubric: rubric || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employer-tasks'] })
      onClose()
    },
  })
  const bp = Object.keys(cat?.specializations.find((s) => s.id === spec)?.blueprint ?? {})
  return (
    <Modal open onClose={onClose} title="Новое регулярное задание">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          m.mutate()
        }}
      >
        <div className="grid grid-cols-2 gap-2">
          {(['auto', 'open'] as const).map((k) => (
            <button type="button" key={k} onClick={() => setKind(k)} className={`rounded-xl border p-3 text-left text-sm ${kind === k ? 'border-brand-500 bg-brand-50' : 'border-line'}`}>
              <div className="font-medium">{k === 'auto' ? 'Автопроверка' : 'Предложить подход'}</div>
              <div className="text-xs text-muted">{k === 'auto' ? 'Уникальный вариант из банка, проверяется сразу' : 'Свободный ответ, оцениваете вы по рубрике'}</div>
            </button>
          ))}
        </div>
        <Field label="Название" required>
          <input className="input" required minLength={3} value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Специализация">
          <select className="input" value={spec} onChange={(e) => setSpec(e.target.value)}>
            {cat?.specializations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </Field>
        {kind === 'auto' ? (
          <Field label="Навык" hint="Кандидату достанется задание по навыку на уровне его грейда">
            <select className="input" value={skill} onChange={(e) => setSkill(e.target.value)}>
              {bp.map((k) => (
                <option key={k} value={k}>
                  {cat?.assessment_skills.find((s) => s.id === k)?.title}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <>
            <Field label="Формулировка" required>
              <textarea className="input min-h-28" required value={prompt} onChange={(e) => setPrompt(e.target.value)} />
            </Field>
            <Field label="Критерии оценки">
              <textarea className="input min-h-16" value={rubric} onChange={(e) => setRubric(e.target.value)} />
            </Field>
          </>
        )}
        <ErrorBox error={m.error} />
        <button className="btn-primary" disabled={m.isPending}>
          Создать
        </button>
      </form>
    </Modal>
  )
}

function Submissions({ t, onClose }: { t: TaskOut; onClose: () => void }) {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['subs', t.id], queryFn: () => api.get<Assignment[]>(`/api/employer/tasks/${t.id}/submissions`) })
  const [scores, setScores] = useState<Record<string, string>>({})
  const review = useMutation({ mutationFn: (x: { id: string; score: number }) => api.post(`/api/employer/submissions/${x.id}/review`, { score: x.score }), onSuccess: () => qc.invalidateQueries({ queryKey: ['subs', t.id] }) })
  return (
    <Modal open onClose={onClose} title={`Решения: ${t.title}`} wide>
      {!data ? (
        <PageLoader />
      ) : data.length === 0 ? (
        <p className="text-sm text-muted">Решений пока нет.</p>
      ) : (
        <div className="space-y-3">
          {data.map((a) => (
            <div key={a.id} className="rounded-xl border border-line p-4 text-sm">
              <div className="flex items-center justify-between">
                <b className="font-mono">{a.candidate_alias}</b>
                <span className="text-xs text-muted">{date(a.submitted_at)}</span>
              </div>
              {t.kind === 'auto' ? (
                <div className={`mt-1 ${a.correct ? 'text-ok-600' : 'text-accent-600'}`}>{a.correct ? 'Верно' : 'Неверно'}</div>
              ) : (
                <>
                  <p className="mt-2 whitespace-pre-wrap text-ink-soft">{String(a.answer?.text ?? '')}</p>
                  <div className="mt-3 flex items-center gap-2">
                    <input className="input w-24" type="number" min={0} max={100} placeholder="0–100" value={scores[a.id] ?? (a.score != null ? String(Math.round(a.score * 100)) : '')} onChange={(e) => setScores({ ...scores, [a.id]: e.target.value })} />
                    <button className="btn-secondary btn-sm" onClick={() => review.mutate({ id: a.id, score: Number(scores[a.id] ?? 0) / 100 })}>
                      Оценить
                    </button>
                    {a.status === 'reviewed' && <Badge tone="bg-ok-50 text-ok-600">оценено</Badge>}
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}

export default function EmployerTasks() {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const [creating, setCreating] = useState(false)
  const [subs, setSubs] = useState<TaskOut | null>(null)
  const { data, isLoading } = useQuery({ queryKey: ['employer-tasks'], queryFn: () => api.get<TaskOut[]>('/api/employer/tasks') })
  if (isLoading || !data) return <PageLoader />
  return (
    <div>
      <PageHeader
        eyebrow="Регулярные задания"
        title="Задания для кандидатов"
        subtitle="Кандидатам вашей специализации раз в две недели предлагается одно задание. Свежие решения обновляют их профиль — вы получаете актуальный сигнал о навыках."
        actions={
          <button className="btn-primary" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> Новое задание
          </button>
        }
      />
      {data.length === 0 ? (
        <EmptyState title="Заданий пока нет" text="Создайте автопроверяемое задание из банка или открытую задачу «предложите подход»." />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.map((t) => (
            <button key={t.id} onClick={() => setSubs(t)} className="card p-5 text-left transition-colors hover:border-brand-300">
              <div className="font-medium">{t.title}</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge tone="bg-brand-50 text-brand-700">{L.spec(t.specialization)}</Badge>
                <Badge>{t.kind === 'auto' ? `автопроверка · ${L.skill(t.skill)}` : 'открытое'}</Badge>
              </div>
              <div className="mt-3 text-xs text-muted">
                Назначено {t.assigned} · решений {t.submitted}
              </div>
            </button>
          ))}
        </div>
      )}
      {creating && <NewTask onClose={() => setCreating(false)} />}
      {subs && <Submissions t={subs} onClose={() => setSubs(null)} />}
    </div>
  )
}
