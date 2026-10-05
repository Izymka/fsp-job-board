import { useQuery } from '@tanstack/react-query'
import { ArrowRight, ClipboardCheck, Download, Mail, Medal } from 'lucide-react'
import { Link } from 'react-router-dom'
import { FspList, SkillList, StatusBadge } from '../../components/domain'
import { Badge, PageHeader, PageLoader, Progress, Section, Stat } from '../../components/ui'
import { api } from '../../lib/api'
import { date, lookup, range, useCatalog } from '../../lib/catalog'
import type { Dashboard, Invitation, Profile } from '../../lib/types'

export default function CandidateHome() {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const dash = useQuery({ queryKey: ['dashboard'], queryFn: () => api.get<Dashboard>('/api/candidate/dashboard') })
  const prof = useQuery({ queryKey: ['profile'], queryFn: () => api.get<Profile>('/api/candidate/profile') })
  const inv = useQuery({ queryKey: ['candidate-invitations'], queryFn: () => api.get<Invitation[]>('/api/candidate/invitations') })
  if (!dash.data || !prof.data) return <PageLoader />
  const d = dash.data
  const p = prof.data
  return (
    <div>
      <PageHeader
        eyebrow="Кабинет кандидата"
        title={p.full_name ? `Здравствуйте, ${p.full_name.split(' ')[1] ?? p.full_name}` : 'Ваш кабинет'}
        actions={
          <button className="btn-secondary" onClick={() => api.download('/api/candidate/profile.pdf', 'fsp-profile.pdf')}>
            <Download className="h-4 w-4" /> PDF-профиль
          </button>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          <section className="card relative overflow-hidden p-6">
            <div className="text-xs tracking-wider text-muted uppercase">Ваша категория</div>
            {d.category ? (
              <>
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <span className="font-mono text-3xl font-bold text-brand-600">{d.category}</span>
                  <Badge tone="bg-ok-50 text-ok-600">подтверждено тестом {date(p.confirmed_at)}</Badge>
                </div>
                <p className="mt-2 text-sm text-muted">
                  Работодатели находят вас в этой категории. {p.search_status === 'closed' ? 'Сейчас вы скрыты из поиска (статус «Не ищу»).' : ''}
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Link to="/candidate/test" className="btn-secondary btn-sm">
                    Повысить грейд
                  </Link>
                  <Link to="/candidate/invitations" className="btn-primary btn-sm">
                    Приглашения {d.invitations_new > 0 && <span className="rounded-full bg-white/25 px-1.5">{d.invitations_new}</span>}
                  </Link>
                </div>
              </>
            ) : (
              <>
                <div className="mt-2 font-mono text-2xl font-bold">Категория не присвоена</div>
                <p className="mt-2 max-w-lg text-sm text-muted">
                  Работодатели видят только кандидатов, подтвердивших грейд тестом. {p.survey_completed_at ? `Заявленный грейд: ${L.grade(p.claimed_grade)} (${L.spec(p.specialization)}).` : 'Начните с короткого опроса.'}
                </p>
                <Link to={p.survey_completed_at ? '/candidate/test' : '/candidate/survey'} className="btn-primary mt-4">
                  <ClipboardCheck className="h-4 w-4" /> {p.survey_completed_at ? 'Пройти тест' : 'Пройти опрос'} <ArrowRight className="h-4 w-4" />
                </Link>
              </>
            )}
          </section>

          {Object.keys(p.skill_scores).length > 0 && (
            <Section title="Навыки по результатам теста">
              <SkillList scores={p.skill_scores} />
            </Section>
          )}

          <Section
            title="Последние приглашения"
            actions={
              <Link to="/candidate/invitations" className="link text-sm">
                Все
              </Link>
            }
          >
            {inv.data?.length ? (
              <ul className="divide-y divide-line">
                {inv.data.slice(0, 4).map((i) => (
                  <li key={i.id} className="flex items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{i.title}</div>
                      <div className="text-xs text-muted">
                        {i.company_name} · {range(i.salary_from, i.salary_to)}
                      </div>
                    </div>
                    <StatusBadge status={i.status} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="flex items-center gap-2 text-sm text-muted">
                <Mail className="h-4 w-4" /> Пока нет приглашений. {d.category ? 'Работодатели увидят ваш профиль в поиске.' : 'Они появятся после подтверждения грейда.'}
              </p>
            )}
          </Section>
        </div>

        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <Stat label="Новые приглашения" value={d.invitations_new} hint={`всего ${d.invitations_total}`} />
            <Stat label="Отклики" value={d.applications_total} />
            <Stat label="Задания" value={d.tasks_open} hint="ожидают решения" />
            <Stat label="Профиль заполнен" value={`${Math.round(d.profile_completeness * 100)}%`} />
          </div>
          {d.next_actions.length > 0 && (
            <Section title="Что сделать дальше">
              <ul className="space-y-2 text-sm">
                {d.next_actions.map((a) => (
                  <li key={a} className="flex gap-2">
                    <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" />
                    {a}
                  </li>
                ))}
              </ul>
              <div className="mt-4">
                <Progress value={d.profile_completeness} />
              </div>
            </Section>
          )}
          <Section
            title={
              <span className="flex items-center gap-2">
                <Medal className="h-4 w-4 text-accent-500" /> Достижения ФСП
              </span>
            }
            actions={
              <Link to="/candidate/settings" className="link text-sm">
                {p.fsp_id ? 'Настроить' : 'Привязать'}
              </Link>
            }
          >
            <FspList items={p.fsp_achievements} linked={!!p.fsp_id} visible={p.show_fsp} />
          </Section>
        </div>
      </div>
    </div>
  )
}
