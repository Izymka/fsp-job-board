import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, Lock, Medal, Play, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BlueprintBars, StatusBadge } from '../../components/domain'
import { ProctorCheckModal, type ProctorStart } from '../../components/proctor'
import { Badge, EmptyState, ErrorBox, Modal, More, Notice, PageHeader, PageLoader, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { date, dateTime, lookup, useCatalog } from '../../lib/catalog'
import { detectEnv, enterFullscreen, isDesktop, screenExtended } from '../../lib/environment'
import { proctor } from '../../lib/proctor/session'
import type { Attempt, Eligibility, GradeId, GrowthPlan, Profile } from '../../lib/types'

const ATTEMPT_STATUS = {
  in_progress: { label: 'В процессе', tone: 'bg-brand-50 text-brand-700' },
  passed: { label: 'Подтверждён', tone: 'bg-ok-50 text-ok-600' },
  failed: { label: 'Не подтверждён', tone: 'bg-warn-50 text-warn-600' },
  abandoned: { label: 'Прервана', tone: 'bg-surface text-muted' },
  voided: { label: 'Аннулирована', tone: 'bg-accent-50 text-accent-600' },
}

export default function TestHub() {
  const catalog = useCatalog()
  const cat = catalog.data
  const L = lookup(cat)
  const qc = useQueryClient()
  const nav = useNavigate()
  const prof = useQuery({ queryKey: ['profile'], queryFn: () => api.get<Profile>('/api/candidate/profile') })
  const elig = useQuery({ queryKey: ['eligibility'], queryFn: () => api.get<Eligibility>('/api/assessment/eligibility') })
  const hist = useQuery({ queryKey: ['attempts'], queryFn: () => api.get<Attempt[]>('/api/assessment/attempts') })
  const [launchFor, setLaunchFor] = useState<GradeId | null>(null)
  const [checkFor, setCheckFor] = useState<GradeId | null>(null)
  const start = useMutation({
    mutationFn: ({ grade, p }: { grade: GradeId; p?: ProctorStart }) => api.post<Attempt>('/api/assessment/attempts', { grade, ...p, env: detectEnv() }),
    onSuccess: (a, v) => {
      qc.invalidateQueries({ queryKey: ['eligibility'] })
      if (v.p) proctor.start(v.p.embeddings)
      nav(`/candidate/test/${a.id}`)
    },
    onError: (_e, v) => {
      if (v.p) proctor.stop()
    },
  })
  const begin = (grade: GradeId, withProctor: boolean) => {
    setLaunchFor(null)
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
        title={e.confirmed_grade ? `${L.spec(e.specialization)} · ${L.grade(e.confirmed_grade)}` : 'Тест на заявленный грейд'}
        subtitle={
          e.confirmed_grade
            ? `Грейд подтверждён ${date(e.confirmed_at)}. Можно подтвердить уровень выше.`
            : `${spec?.title} · заявлено ${L.grade(e.claimed_grade)}. Около 30–40 минут, задания подстраиваются под ваши ответы.`
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
                    <button className={clsx('mt-3 w-full', recommended ? 'btn-primary' : 'btn-secondary')} disabled={start.isPending || !!e.in_progress} onClick={() => setLaunchFor(o.grade)}>
                      <Play className="h-4 w-4" /> Начать
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
          <div className="mt-3">
            <ErrorBox error={start.error} />
          </div>
          <LaunchModal grade={launchFor} label={launchFor ? L.grade(launchFor) : ''} onClose={() => setLaunchFor(null)} onStart={begin} />
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
        <Section title="О тесте">
          <p className="text-sm text-ink-soft">
            Проверяем ядро специализации и только заявленный стек. Не подтвердили — грейд не понизим. У заданий есть рекомендуемое время; уходы со страницы на трёх заданиях аннулируют попытку.
          </p>
          <More label="Правила" className="mt-4">
            <ul className="space-y-2 text-sm text-ink-soft">
              {e.rules.map((r) => (
                <li key={r} className="flex gap-2">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-500" />
                  {r}
                </li>
              ))}
            </ul>
          </More>
          {bp && (
            <More label="Что проверяет тест" className="mt-3">
              <div className="mb-2 text-xs font-medium text-muted">Ядро специализации</div>
              <BlueprintBars blueprint={pick(bp.core)} label={L.skill} max={bpMax} />
              {bp.modules.length > 0 && (
                <>
                  <div className="mt-4 mb-2 text-xs font-medium text-muted">Модули по вашему стеку</div>
                  <BlueprintBars blueprint={pick(bp.modules.map((m) => m.skill))} label={L.skill} max={bpMax} />
                </>
              )}
              <p className="hint mt-3">
                Стек можно изменить в <Link to="/candidate/survey" className="link">опросе</Link>.
              </p>
            </More>
          )}
        </Section>
      </div>

      {hist.data?.some((a) => a.status !== 'in_progress') && <GrowthSection />}

      {hist.data && hist.data.length > 0 && (
        <Section title="История попыток" className="mt-6">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr>
                  <th className="py-2 pr-3 font-medium">Дата</th>
                  <th className="py-2 pr-3 font-medium">Грейд</th>
                  <th className="py-2 pr-3 font-medium">Результат</th>
                  <th />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {hist.data.map((a) => (
                  <tr key={a.id}>
                    <td className="py-2.5 pr-3 whitespace-nowrap">{dateTime(a.started_at)}</td>
                    <td className="py-2.5 pr-3 font-mono font-semibold">{L.grade(a.grade)}</td>
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
    </div>
  )
}

/** Окно запуска теста: проктор включён по умолчанию, отказ от него — с явным предупреждением о потере в выдаче. */
function LaunchModal({ grade, label, onClose, onStart }: { grade: GradeId | null; label: string; onClose: () => void; onStart: (g: GradeId, withProctor: boolean) => void }) {
  const [withProctor, setWithProctor] = useState(true)
  const close = () => {
    setWithProctor(true)
    onClose()
  }
  return (
    <Modal open={grade != null} onClose={close} title={`Тест на грейд ${label}`}>
      <label className={clsx('flex cursor-pointer items-start gap-3 rounded-xl border p-4', withProctor ? 'border-brand-500 bg-brand-50' : 'border-line')}>
        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-500" checked={withProctor} onChange={(ev) => setWithProctor(ev.target.checked)} />
        <span className="text-sm">
          <span className="flex items-center gap-1.5 font-semibold">
            <ShieldCheck className="h-4 w-4 text-brand-600" /> Пройти с цифровым проктором
          </span>
          <span className="mt-0.5 block text-xs text-muted">
            Камера и микрофон анализируются в браузере, видео не записывается. Ручка и лист для расчётов — можно. Работодатель увидит отметку «Тест с проктором».
          </span>
        </span>
      </label>
      {!withProctor && (
        <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-warn-600/30 bg-warn-50 p-4 text-sm text-warn-600">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            <b>Без проктора вы будете ниже в выдаче.</b> При сопоставимом соответствии вакансии кандидаты с проктором стоят выше. Работодатель увидит пометку «Тест без проктора».
          </span>
        </div>
      )}
      <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button className="btn-secondary" onClick={close}>
          Отмена
        </button>
        <button
          className="btn-primary"
          onClick={() => {
            const g = grade!
            const p = withProctor
            setWithProctor(true)
            onStart(g, p)
          }}
        >
          <Play className="h-4 w-4" /> {withProctor ? 'Продолжить с проктором' : 'Начать без проктора'}
        </button>
      </div>
    </Modal>
  )
}

function GrowthSection() {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const q = useQuery({ queryKey: ['fsp-growth'], queryFn: () => api.get<GrowthPlan>('/api/fsp/growth') })
  const g = q.data
  if (!g || (!g.weak_skills.length && !g.events.length)) return null
  return (
    <Section title="План роста" className="mt-6">
      <div className="grid gap-6 md:grid-cols-2">
        {g.weak_skills.length > 0 && (
          <div>
            <div className="mb-2 text-xs font-medium text-muted">Что подтянуть по итогам теста</div>
            <div className="flex flex-wrap gap-1.5">
              {g.weak_skills.map((s) => (
                <Badge key={s} tone="bg-warn-50 text-warn-600">
                  {L.skill(s)}
                </Badge>
              ))}
            </div>
            <p className="hint mt-2">Повторить тест на этот же уровень можно через 14 дней — на других заданиях.</p>
          </div>
        )}
        {g.events.length > 0 && (
          <div>
            <div className="mb-2 text-xs font-medium text-muted">Ближайшие соревнования ФСП по вашей специализации</div>
            <ul className="space-y-2">
              {g.events.map((e) => (
                <li key={e.id} className="flex items-start gap-2 text-sm">
                  <Medal className="mt-0.5 h-4 w-4 shrink-0 text-accent-500" />
                  <span>
                    <span className="font-medium">{e.title}</span>
                    <span className="block text-xs text-muted">
                      {date(e.start_date)}
                      {e.city ? ` · ${e.city}` : ''} · {L.fspLevel(e.level)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="hint mt-2">Призовое место в реестре ФСП засчитывается работодателями как практический опыт и учитывается в подборе.</p>
          </div>
        )}
      </div>
    </Section>
  )
}
