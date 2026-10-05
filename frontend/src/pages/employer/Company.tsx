import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ErrorBox, Field, PageHeader, PageLoader, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { useCatalog } from '../../lib/catalog'
import type { Company } from '../../lib/types'

const FIELDS = ['name', 'description', 'industry', 'website', 'city', 'contact_email', 'contact_phone', 'contact_telegram', 'inn', 'webhook_url'] as const
type Form = Record<(typeof FIELDS)[number], string>

export default function EmployerCompany() {
  const { data: cat } = useCatalog()
  const qc = useQueryClient()
  const nav = useNavigate()
  const { data, isLoading } = useQuery({ queryKey: ['company'], queryFn: () => api.get<Company | null>('/api/employer/company') })
  const [f, setF] = useState<Form>(Object.fromEntries(FIELDS.map((k) => [k, ''])) as Form)
  useEffect(() => {
    if (data) setF(Object.fromEntries(FIELDS.map((k) => [k, (data[k] as string) ?? ''])) as Form)
  }, [data])
  const save = useMutation({
    mutationFn: () => api.put<Company>('/api/employer/company', Object.fromEntries(FIELDS.map((k) => [k, f[k] || null]))),
    onSuccess: (d) => {
      const isNew = !data
      qc.setQueryData(['company'], d)
      qc.invalidateQueries({ queryKey: ['me'] })
      if (isNew) nav('/employer/searches/new')
    },
  })
  if (isLoading) return <PageLoader />
  const set = (k: keyof Form) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader eyebrow={data ? 'Компания' : 'Шаг 2 из 2'} title="Профиль компании" subtitle="Кандидат видит компанию в приглашении: название, направление деятельности и описание помогают принять решение." />
      <form
        className="space-y-6"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <Section title="О компании">
          <div className="space-y-4">
            <Field label="Название" required>
              <input className="input" required minLength={2} value={f.name} onChange={set('name')} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Отрасль">
                <select className="input" value={f.industry} onChange={set('industry')}>
                  <option value="">—</option>
                  {cat?.industries.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.title}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Город">
                <input className="input" value={f.city} onChange={set('city')} />
              </Field>
            </div>
            <Field label="Описание" hint="Чем занимается компания, продукты, команда">
              <textarea className="input min-h-28" value={f.description} onChange={set('description')} />
            </Field>
            <Field label="Сайт">
              <input className="input" value={f.website} onChange={set('website')} placeholder="https://" />
            </Field>
          </div>
        </Section>
        <Section title="Контакты">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Email">
              <input className="input" type="email" value={f.contact_email} onChange={set('contact_email')} />
            </Field>
            <Field label="Телефон">
              <input className="input" value={f.contact_phone} onChange={set('contact_phone')} />
            </Field>
            <Field label="Telegram">
              <input className="input" value={f.contact_telegram} onChange={set('contact_telegram')} />
            </Field>
          </div>
        </Section>
        <Section title="Дополнительно">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="ИНН" hint="Задел для верификации работодателя (вне MVP)">
              <input className="input" value={f.inn} onChange={set('inn')} pattern="\d{10}(\d{2})?" />
            </Field>
            <Field label="Webhook для ATS" hint="POST-событие при принятии приглашения (JSON с контактами кандидата)">
              <input className="input" value={f.webhook_url} onChange={set('webhook_url')} placeholder="https://ats.example.ru/hooks/fsp" />
            </Field>
          </div>
        </Section>
        <ErrorBox error={save.error} />
        <button className="btn-primary px-6" disabled={save.isPending}>
          {data ? 'Сохранить' : 'Сохранить и описать потребность'}
        </button>
        {save.isSuccess && data && <span className="ml-3 text-sm text-ok-600">Сохранено</span>}
      </form>
    </div>
  )
}
