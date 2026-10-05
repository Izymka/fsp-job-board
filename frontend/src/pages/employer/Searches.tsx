import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, EmptyState, PageHeader, PageLoader } from '../../components/ui'
import { api } from '../../lib/api'
import { date } from '../../lib/catalog'
import type { SearchSummary } from '../../lib/types'

export default function Searches() {
  const { data, isLoading } = useQuery({ queryKey: ['searches'], queryFn: () => api.get<SearchSummary[]>('/api/employer/searches') })
  if (isLoading || !data) return <PageLoader />
  return (
    <div>
      <PageHeader
        eyebrow="Подборки"
        title="Сохранённые подборки"
        subtitle="Каждая подборка — описание потребности и версии уточнений. Результаты пересчитываются при открытии: новые кандидаты попадают в выдачу автоматически."
        actions={
          <Link to="/employer/searches/new" className="btn-primary">
            <Plus className="h-4 w-4" /> Новая подборка
          </Link>
        }
      />
      {data.length === 0 ? (
        <EmptyState title="Подборок пока нет" text="Опишите потребность — получите кандидатов с объяснением." action={<Link to="/employer/searches/new" className="btn-primary">Описать потребность</Link>} />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.map((s) => (
            <Link key={s.id} to={`/employer/searches/${s.id}`} className="card p-5 transition-colors hover:border-brand-300">
              <div className="font-mono font-bold">{s.title}</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge tone="bg-brand-50 text-brand-700">{s.category}</Badge>
                <Badge>версия {s.version}</Badge>
                <Badge>шорт-лист {s.shortlist}</Badge>
              </div>
              <div className="mt-2 text-xs text-muted">обновлена {date(s.updated_at)}</div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
