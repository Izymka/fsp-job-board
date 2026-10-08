import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Clock, Lock, Play, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BlueprintBars, StatusBadge } from '../../components/domain'
import { ProctorCheckModal, type ProctorStart } from '../../components/proctor'
import { Badge, EmptyState, ErrorBox, Notice, PageHeader, PageLoader, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { date, dateTime, lookup, useCatalog } from '../../lib/catalog'
import { detectEnv, enterFullscreen, isDesktop, screenExtended } from '../../lib/environment'
import { proctor } from '../../lib/proctor/session'
import type { Attempt, Eligibility, GradeId, Profile } from '../../lib/types'

const ATTEMPT_STATUS = {
  in_progress: { label: 'В процессе', tone: 'bg-brand-50 text-brand-700' },
  passed: { label: 'Подтверждён', tone: 'bg-ok-50 text-ok-600' },
  failed: { label: 'Не подтверждён', tone: 'bg-warn-50 text-warn-600' },
  abandoned: { label: 'Прервана', tone: 'bg-surface text-muted' },
  voided: { label: 'Аннулирована', tone: 'bg-accent-50 text-accent-600' },
}
const KIND = { initial: 'первичный', upgrade: 'повышение', downgrade: 'уровень ниже', refresh: 'обновление результата' } as Record<string, string>

export default function TestHub() {
  const catalog = useCatalog()
  const cat = catalog.data
  const L = lookup(cat)
  const qc = useQueryClient()
  const nav = useNavigate()
  const prof = useQuery({ queryKey: ['profile'], queryFn: () => api.get<Profile>('/api/candidate/profile') })
  const elig = useQuery({ queryKey: ['eligibility'], queryFn: () => api.get<Eligibility>('/api/assessment/eligibility') })
  const hist = useQuery({ queryKey: ['attempts'], queryFn: () => api.get<Attempt[]>('/api/assessment/attempts') })
  const [withProctor, setWithProctor] = useState(false)
  const [checkFor, setCheckFor] = useState<GradeId | null>(null)
  const start = useMutation({
    mutationFn: ({ grade, p }: { grade: GradeId; p?: ProctorStart }) => api.post<Attempt>('/api/assessment/attempts', { grade, ...p, env: detectEnv() }),
    onSuccess: (a, v) => {
      qc.invalidateQueries({ queryKey: ['eligibility'] })
      if (v.p) proctor.start(v.p.embedding)
      nav(`/candidate/test/${a.id}`)
    },
    onError: (_e, v) => {
      if (v.p) proctor.stop()
    },
  })
  const begin = (grade: GradeId) => {
    if (withProctor) return setCheckFor(grade)
    void enterFullscreen() // синхронно в обработчике клика — требование браузера
    start.mutate({ grade })
  }
  if (!elig.data || !prof.data || !cat) return <PageLoader queries={[elig, prof, catalog]} />
  const e = elig.data
  const p = prof.data
  if (!p.survey_completed_at)
    return <EmptyState title="Сначала опрос" text="Специализация и стек определяют содержание теста." action={<Link to="/candidate/survey" className="btn-primary">Пройти опрос</Link>} />
  const spec = cat.specializations.find((s) => s.id === p.specialization)
  const bp = e.blueprint
  const pick = (keys: string[]) => Object.fromEntries(keys.filter((k) => bp && k in bp.weights).map((k) => [k, bp!.weights[k]]))
  const bpMax = bp ? Math.max(...Object.values(bp.weights), 0.01) : undefined
  return (
    <div>
      <PageHeader
        eyebrow="Шаг 3 из 3 · Тестирование"
        title={e.confirmed_grade ? `${L.spec(e.specialization)} · ${L.grade(e.confirmed_grade)}` : 'Тест на заявленный грейд'}
        subtitle={
          e.confirmed_grade
            ? `Грейд подтверждён ${date(e.confirmed_at)}. Можно попробовать подтвердить уровень выше — по правилам смены грейда.`
            : `Специализация: ${spec?.title}. Заявленный грейд: ${L.grade(e.claimed_grade)}. Тест займёт 20–30 минут: 10–25 заданий, подобранных под ваши ответы.`
        }
      />
      {e.in_progress && (
        <div className="mb-6">
          <div className="card flex flex-col items-start justify-between gap-3 border-brand-300 bg-brand-50 p-4 sm:flex-row sm:items-center">
            <div className="text-sm">
              <b>У вас есть незавершённая попытка.</b> Её можно продолжить — брошенная попытка засчитывается как неудачная.
            </div>
            <Link to={`/candidate/test/${e.in_progress}`} className="btn-primary">
              <Play className="h-4 w-4" /> Продолжить
            </Link>
          </div>
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Section title="Выберите уровень">
          <div className="grid gap-3 sm:grid-cols-2">
            {e.options.map((o) => {
              const g = cat.grades.find((x) => x.id === o.grade)!
              const recommended = !e.confirmed_grade ? o.grade === e.claimed_grade : o.kind === 'upgrade'
              return (
                <div key={o.grade} className={clsx('rounded-xl border p-4', recommended && o.allowed ? 'border-brand-500 ring-2 ring-brand-100' : 'border-line', !o.allowed && 'bg-surface')}>
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-lg font-bold">{g.name}</span>
                    {e.confirmed_grade === o.grade ? <Badge tone="bg-ok-50 text-ok-600">ваш грейд</Badge> : recommended && o.allowed ? <Badge tone="bg-brand-50 text-brand-700">рекомендуем</Badge> : null}
                  </div>
                  <div className="mt-0.5 text-xs text-muted">
                    {g.title} · {g.experience}
                  </div>
                  {o.allowed ? (
                    <button className={clsx('mt-3 w-full', recommended ? 'btn-primary' : 'btn-secondary')} disabled={start.isPending || !!e.in_progress} onClick={() => begin(o.grade)}>
                      <Play className="h-4 w-4" /> Начать ({KIND[o.kind] ?? o.kind})
                    </button>
                  ) : (
                    <div className="mt-3 flex items-start gap-2 text-xs text-muted">
                      <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      <span>
                        {o.reason}
                        {o.available_at && ` — доступно с ${date(o.available_at)}`}
                      </span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          {isDesktop() && (
            <p className="hint mt-4">Тест откроется в полноэкранном режиме. Выход из него засчитывается как уход со страницы.</p>
          )}
          {screenExtended() && (
            <div className="mt-3">
              <Notice tone="warn">Подключён второй монитор. Отключите его до начала теста — иначе работодатель увидит замечание.</Notice>
            </div>
          )}
          <label className={clsx('mt-4 flex cursor-pointer items-start gap-3 rounded-xl border p-4', withProctor ? 'border-brand-500 bg-brand-50' : 'border-line')}>
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-500" checked={withProctor} onChange={(ev) => setWithProctor(ev.target.checked)} />
            <span className="text-sm">
              <span className="flex items-center gap-1.5 font-semibold">
                <ShieldCheck className="h-4 w-4 text-brand-600" /> Пройти с цифровым проктором
              </span>
              <span className="mt-0.5 block text-xs text-muted">
                По желанию. Камера и микрофон анализируются в браузере, видео не записывается. Работодатель увидит отметку «Тест с проктором», а при равных результатах такой профиль стоит выше.
              </span>
            </span>
          </label>
          <div className="mt-3">
            <ErrorBox error={start.error} />
          </div>
          <ProctorCheckModal
            open={checkFor != null}
            onClose={() => setCheckFor(null)}
            onReady={(p) => {
              const grade = checkFor!
              setCheckFor(null)
              void enterFullscreen()
              start.mutate({ grade, p })
            }}
          />
        </Section>
        <div className="space-y-6">
          <Section title="Правила">
            <ul className="space-y-2 text-sm text-ink-soft">
              {e.rules.map((r) => (
                <li key={r} className="flex gap-2">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-500" />
                  {r}
                </li>
              ))}
            </ul>
          </Section>
          {bp && (
            <Section title="Что проверяет тест">
              <div className="mb-2 text-xs font-medium text-muted">Ядро специализации — общее для всех в категории</div>
              <BlueprintBars blueprint={pick(bp.core)} label={L.skill} max={bpMax} />
              {bp.modules.length > 0 && (
                <>
                  <div className="mt-4 mb-2 text-xs font-medium text-muted">Модули по направлению и стеку</div>
                  <BlueprintBars blueprint={pick(bp.modules.map((m) => m.skill))} label={L.skill} max={bpMax} />
                  <p className="hint mt-2">
                    {bp.modules.map((m) => `${L.skill(m.skill)} — ${m.techs.join(', ')}`).join('; ')}
                  </p>
                </>
              )}
              <p className="hint mt-3">
                Технологии, которых нет в вашем стеке, в тест не попадают.
                {bp.untested.length > 0 && ` Без отдельных заданий: ${bp.untested.join(', ')} — вместо них ничего не подставляется, в профиле они остаются заявленными.`}{' '}
                Стек можно изменить в <Link to="/candidate/survey" className="link">опросе</Link>.
              </p>
            </Section>
          )}
        </div>
      </div>

      {hist.data && hist.data.length > 0 && (
        <Section title="История попыток" className="mt-6">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr>
                  <th className="py-2 pr-3 font-medium">Дата</th>
                  <th className="py-2 pr-3 font-medium">Грейд</th>
                  <th className="py-2 pr-3 font-medium">Тип</th>
                  <th className="py-2 pr-3 font-medium">Заданий</th>
                  <th className="py-2 pr-3 font-medium">Результат</th>
                  <th />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {hist.data.map((a) => (
                  <tr key={a.id}>
                    <td className="py-2.5 pr-3 whitespace-nowrap">{dateTime(a.started_at)}</td>
                    <td className="py-2.5 pr-3 font-mono font-semibold">{L.grade(a.grade)}</td>
                    <td className="py-2.5 pr-3 text-muted">{KIND[a.kind] ?? a.kind}</td>
                    <td className="py-2.5 pr-3">{a.result?.n_items ?? a.answered}</td>
                    <td className="py-2.5 pr-3">
                      <StatusBadge status={a.status} map={ATTEMPT_STATUS} />
                    </td>
                    <td className="py-2.5 text-right">
                      <Link to={`/candidate/test/${a.id}`} className="link text-xs">
                        {a.status === 'in_progress' ? 'Продолжить' : 'Подробнее'}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
      <p className="mt-4 flex items-center gap-1.5 text-xs text-muted">
        <Clock className="h-3.5 w-3.5" /> На каждое задание — ограничение по времени. Уход со страницы теста фиксируется: уходы на трёх заданиях аннулируют попытку.
      </p>
    </div>
  )
}
