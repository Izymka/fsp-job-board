import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { SalaryFit, StatusBadge } from '../../components/domain'
import { EmptyState, PageHeader, PageLoader, Tabs } from '../../components/ui'
import { api } from '../../lib/api'
import { dateTime, INVITE_STATUS, lookup, range, useCatalog } from '../../lib/catalog'
import type { Invitation } from '../../lib/types'
import { useState } from 'react'

export default function EmployerInvitations() {
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const qc = useQueryClient()
  const [tab, setTab] = useState<string>('all')
  const invs = useQuery({ queryKey: ['employer-invitations'], queryFn: () => api.get<Invitation[]>('/api/employer/invitations') })
  const data = invs.data
  const withdraw = useMutation({ mutationFn: (id: string) => api.post(`/api/employer/invitations/${id}/withdraw`), onSuccess: () => qc.invalidateQueries({ queryKey: ['employer-invitations'] }) })
  if (!data) return <PageLoader queries={[invs]} />
  const counts = data.reduce<Record<string, number>>((a, i) => ((a[i.status] = (a[i.status] ?? 0) + 1), a), {})
  const rows = tab === 'all' ? data : data.filter((i) => i.status === tab)
  return (
    <div>
      <PageHeader title="Приглашения" subtitle="После принятия здесь появятся ФИО и контакты кандидата." />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[{ id: 'all', label: `Все (${data.length})` }, ...Object.keys(INVITE_STATUS).filter((k) => counts[k]).map((k) => ({ id: k, label: `${INVITE_STATUS[k].label} (${counts[k]})` }))]}
      />
      {rows.length === 0 ? (
        <EmptyState title="Приглашений нет" text="Найдите кандидатов в подборке или банке и пригласите их с предложением и вилкой." action={<Link to="/employer/searches/new" className="btn-primary">Новая подборка</Link>} />
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-3 font-medium">Кандидат</th>
                <th className="px-4 py-3 font-medium">Предложение</th>
                <th className="px-4 py-3 font-medium">Вилка</th>
                <th className="px-4 py-3 font-medium">Статус</th>
                <th className="px-4 py-3 font-medium">Контакты</th>
                <th />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((i) => (
                <tr key={i.id} className="align-top">
                  <td className="px-4 py-3">
                    <Link to={`/employer/candidates/${i.candidate_id}`} className="font-medium hover:text-brand-600">
                      {i.candidate_name ?? i.candidate_alias}
                    </Link>
                    <div className="text-xs text-muted">{i.candidate_category}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div>{i.title}</div>
                    <div className="text-xs text-muted">{dateTime(i.created_at)}</div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="font-mono">{range(i.salary_from, i.salary_to)}</div>
                    <SalaryFit fit={i.salary_fit} />
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={i.status} />
                    {i.decline_reason && <div className="mt-1 text-xs text-muted">{L.reason(i.decline_reason)}</div>}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {i.candidate_contacts ? (
                      Object.entries(i.candidate_contacts).map(([k, v]) => (
                        <div key={k} className="font-mono">
                          {v}
                        </div>
                      ))
                    ) : (
                      <span className="text-muted">после принятия</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {(i.status === 'sent' || i.status === 'viewed') && (
                      <button className="btn-ghost btn-sm" onClick={() => window.confirm('Отозвать приглашение?') && withdraw.mutate(i.id)}>
                        Отозвать
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
