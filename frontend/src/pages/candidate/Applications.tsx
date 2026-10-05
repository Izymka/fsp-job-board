import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { StatusBadge } from '../../components/domain'
import { EmptyState, PageHeader, PageLoader } from '../../components/ui'
import { api } from '../../lib/api'
import { APP_STATUS, date } from '../../lib/catalog'
import type { Application } from '../../lib/types'

export default function CandidateApplications() {
  const { data, isLoading } = useQuery({ queryKey: ['applications'], queryFn: () => api.get<Application[]>('/api/candidate/applications') })
  if (isLoading || !data) return <PageLoader />
  return (
    <div>
      <PageHeader eyebrow="Вакансии" title="Мои отклики" actions={<Link to="/candidate/vacancies" className="btn-secondary">К вакансиям</Link>} />
      {data.length === 0 ? (
        <EmptyState title="Вы ещё не откликались" text="Главный сценарий платформы — приглашения от работодателей, но откликнуться самостоятельно тоже можно." action={<Link to="/candidate/vacancies" className="btn-primary">Смотреть вакансии</Link>} />
      ) : (
        <div className="card divide-y divide-line">
          {data.map((a) => (
            <div key={a.id} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{a.vacancy_title}</div>
                <div className="text-sm text-muted">
                  {a.company_name} · отклик {date(a.created_at)}
                  {a.employer_comment && ` · «${a.employer_comment}»`}
                </div>
              </div>
              <StatusBadge status={a.status} map={APP_STATUS} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
