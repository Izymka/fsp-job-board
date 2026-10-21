import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Notice, PageHeader, PageLoader, Section, Tabs } from '../../components/ui'
import { api } from '../../lib/api'
import type { Funnel, FunnelRow } from '../../lib/types'

const share = (n: number | null | undefined, of: number | null | undefined) => (n != null && of ? `${Math.round((n / of) * 100)}%` : '—')

function Bars({ f }: { f: Funnel }) {
  const top = f.fsp.counts.registered ?? 0
  return (
    <div className="space-y-2.5">
      {f.stages.map((s) => {
        const n = f.fsp.counts[s.id]
        const b = f.baseline.counts[s.id]
        return (
          <div key={s.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-sm sm:grid-cols-[minmax(0,14rem)_1fr_9rem]">
            <span className="truncate text-ink-soft sm:col-start-1 sm:row-start-1" title={s.title}>
              {s.title}
            </span>
            <div className="col-span-2 row-start-2 h-6 overflow-hidden rounded-md bg-surface sm:col-span-1 sm:col-start-2 sm:row-start-1">
              <div className="h-full rounded-md bg-brand-500" style={{ width: `${top && n ? Math.max(2, (n / top) * 100) : 0}%` }} />
            </div>
            <span className="text-right font-mono text-xs whitespace-nowrap sm:col-start-3 sm:row-start-1">
              <b>{n ?? `< ${f.min_cell}`}</b> <span className="text-muted">· без ФСП {share(b, f.baseline.counts.registered)}</span>
            </span>
          </div>
        )
      })}
    </div>
  )
}

function Table({ rows, stages, minCell }: { rows: FunnelRow[]; stages: Funnel['stages']; minCell: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted">
          <tr>
            <th className="py-2 pr-3 font-medium">Группа</th>
            {stages.map((s) => (
              <th key={s.id} className="py-2 pr-3 text-right font-medium">
                {s.title}
              </th>
            ))}
            <th className="py-2 text-right font-medium">Конверсия в работу</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr key={r.key}>
              <td className="py-2.5 pr-3">{r.title}</td>
              {stages.map((s) => (
                <td key={s.id} className="py-2.5 pr-3 text-right font-mono">
                  {r.counts[s.id] ?? <span className="text-muted">{`< ${minCell}`}</span>}
                </td>
              ))}
              <td className="py-2.5 text-right font-mono font-semibold">{share(r.counts.hired, r.counts.registered)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const CUTS = [
  { id: 'by_level', label: 'Уровень соревнования' },
  { id: 'by_discipline', label: 'Дисциплина' },
  { id: 'by_specialization', label: 'Специализация' },
  { id: 'by_region', label: 'Регион' },
] as const

export default function FspFunnel() {
  const q = useQuery({ queryKey: ['fsp-funnel'], queryFn: () => api.get<Funnel>('/api/fsp/funnel') })
  const [cut, setCut] = useState<(typeof CUTS)[number]['id']>('by_level')
  const f = q.data
  if (!f) return <PageLoader queries={[q]} />
  return (
    <div>
      <PageHeader
        eyebrow="Федерация спортивного программирования"
        title="Трудоустройство участников ФСП"
        subtitle="Путь участников с привязанным ФСП ID: от регистрации до выхода на работу — в сравнении с кандидатами без ФСП."
      />
      <Section title="Воронка">
        <Bars f={f} />
        <p className="hint mt-3">
          Конверсия в работу: участники ФСП — <b>{share(f.fsp.counts.hired, f.fsp.counts.registered)}</b>, без ФСП — {share(f.baseline.counts.hired, f.baseline.counts.registered)}. «Вышли на работу» отмечает работодатель по
          принятому приглашению или отклику.
        </p>
      </Section>
      <Section title="Разрезы" className="mt-6" actions={<Tabs value={cut} onChange={setCut} items={CUTS.map((c) => ({ id: c.id, label: c.label }))} />}>
        <Table rows={f[cut]} stages={f.stages} minCell={f.min_cell} />
      </Section>
      <div className="mt-6">
        <Notice>
          Только агрегаты, без персональных данных. Группы меньше {f.min_cell} человек не раскрываются: по редкому сочетанию (регион и дисциплина) можно узнать конкретного участника. Кандидаты, скрывшие ФСП в настройках приватности, в
          статистике ФСП не участвуют.
        </Notice>
      </div>
    </div>
  )
}
