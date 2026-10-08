import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileUp, Plus, Trash2, Wand2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ErrorBox, Field, Notice, PageHeader, PageLoader, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { useCatalog } from '../../lib/catalog'
import type { Job, Profile } from '../../lib/types'

interface ResumeParse {
  parsed: Record<string, unknown>
  suggestions: {
    full_name: string | null
    contact_email: string | null
    phone: string | null
    telegram: string | null
    github: string | null
    city: string | null
    about: string | null
    headline: string | null
    experience_years: number
    soft_skills: string[]
    experience: Job[]
    stack: string[]
    specialization: string | null
    claimed_grade: string | null
    grade_reason: string | null
  }
  warnings: string[]
}

type Form = {
  full_name: string
  contact_email: string
  phone: string
  telegram: string
  github: string
  city: string
  headline: string
  about: string
  experience_years: string
  soft_skills: string
  education: string
  experience: Job[]
}

const empty: Form = { full_name: '', contact_email: '', phone: '', telegram: '', github: '', city: '', headline: '', about: '', experience_years: '', soft_skills: '', education: '', experience: [] }

export default function CandidateProfile() {
  const qc = useQueryClient()
  const profile = useQuery({ queryKey: ['profile'], queryFn: () => api.get<Profile>('/api/candidate/profile') })
  const p = profile.data
  const { data: cat } = useCatalog()
  const [f, setF] = useState<Form>(empty)
  const [parsed, setParsed] = useState<ResumeParse | null>(null)
  const [saved, setSaved] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (!p) return
    setF({
      full_name: p.full_name ?? '',
      contact_email: p.contact_email ?? '',
      phone: p.phone ?? '',
      telegram: p.telegram ?? '',
      github: p.github ?? '',
      city: p.city ?? '',
      headline: p.headline ?? '',
      about: p.about ?? '',
      experience_years: p.experience_years != null ? String(p.experience_years) : '',
      soft_skills: p.soft_skills.join(', '),
      education: p.education ?? '',
      experience: p.experience ?? [],
    })
  }, [p])
  const upload = useMutation({
    mutationFn: (file: File) => api.upload<ResumeParse>('/api/candidate/resume', file),
    onSuccess: (r) => setParsed(r),
  })
  const save = useMutation({
    mutationFn: () =>
      api.put<Profile>('/api/candidate/profile', {
        ...f,
        experience_years: f.experience_years ? Number(f.experience_years) : null,
        soft_skills: f.soft_skills.split(',').map((s) => s.trim()).filter(Boolean),
        experience: f.experience.filter((j) => j.title),
        contact_email: f.contact_email || null,
      }),
    onSuccess: (d) => {
      qc.setQueryData(['profile'], d)
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    },
  })
  const applySuggestions = () => {
    if (!parsed) return
    const s = parsed.suggestions
    setF((x) => ({
      ...x,
      full_name: s.full_name || x.full_name,
      contact_email: s.contact_email || x.contact_email,
      phone: s.phone || x.phone,
      telegram: s.telegram || x.telegram,
      github: s.github || x.github,
      city: s.city || x.city,
      about: s.about || x.about,
      headline: s.headline || x.headline,
      experience_years: s.experience_years ? String(s.experience_years) : x.experience_years,
      soft_skills: s.soft_skills.length ? s.soft_skills.join(', ') : x.soft_skills,
      experience: s.experience.length ? s.experience : x.experience,
    }))
  }
  if (!p) return <PageLoader queries={[profile]} />
  const set = (k: keyof Form) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  return (
    <div>
      <PageHeader
        eyebrow="Профиль"
        title="Профиль и резюме"
        subtitle="Заполните вручную или загрузите PDF — поля распознаются автоматически. ФИО и контакты работодатель увидит только после того, как вы примете приглашение или откликнетесь сами."
        actions={
          <button className="btn-secondary" onClick={() => api.download('/api/candidate/profile.pdf', 'fsp-profile.pdf')}>
            <Download className="h-4 w-4" /> Стандартизированный PDF
          </button>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <form
          className="space-y-6"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <Section title="Личные данные и контакты" actions={<span className="text-xs text-muted">скрыты до контакта</span>}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="ФИО">
                <input className="input" value={f.full_name} onChange={set('full_name')} />
              </Field>
              <Field label="Город">
                <input className="input" value={f.city} onChange={set('city')} />
              </Field>
              <Field label="Email для связи">
                <input className="input" type="email" value={f.contact_email} onChange={set('contact_email')} />
              </Field>
              <Field label="Телефон">
                <input className="input" value={f.phone} onChange={set('phone')} placeholder="+7 900 000-00-00" />
              </Field>
              <Field label="Telegram">
                <input className="input" value={f.telegram} onChange={set('telegram')} placeholder="@username" />
              </Field>
              <Field label="GitHub">
                <input className="input" value={f.github} onChange={set('github')} placeholder="username" />
              </Field>
            </div>
          </Section>

          <Section title="О себе" actions={<span className="text-xs text-muted">видно работодателям</span>}>
            <div className="space-y-4">
              <Field label="Заголовок профиля" hint="Например: «Backend-разработчик, платёжные системы»">
                <input className="input" value={f.headline} onChange={set('headline')} />
              </Field>
              <Field label="О себе">
                <textarea className="input min-h-28" value={f.about} onChange={set('about')} />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Опыт, лет">
                  <input className="input" type="number" step="0.5" min={0} value={f.experience_years} onChange={set('experience_years')} />
                </Field>
                <Field label="Софт-скиллы" hint="Через запятую">
                  <input className="input" value={f.soft_skills} onChange={set('soft_skills')} />
                </Field>
              </div>
              <Field label="Образование">
                <textarea className="input min-h-16" value={f.education} onChange={set('education')} />
              </Field>
            </div>
          </Section>

          <Section
            title="Опыт работы"
            actions={
              <button type="button" className="btn-secondary btn-sm" onClick={() => setF({ ...f, experience: [...f.experience, { title: '', start: '', end: '', description: '' }] })}>
                <Plus className="h-3.5 w-3.5" /> Добавить
              </button>
            }
          >
            <p className="hint mb-3">Укажите роль на каждом месте работы: работодателю важен опыт именно в вашей специализации.</p>
            {f.experience.length === 0 && <p className="text-sm text-muted">Пока пусто.</p>}
            <div className="space-y-3">
              {f.experience.map((j, i) => (
                <div key={i} className="rounded-xl border border-line p-3">
                  <div className="grid gap-2 sm:grid-cols-[1fr_7rem_7rem_auto]">
                    <input className="input" placeholder="Должность, компания" value={j.title} onChange={(e) => setF({ ...f, experience: f.experience.map((x, k) => (k === i ? { ...x, title: e.target.value } : x)) })} />
                    <input className="input" placeholder="Начало" value={j.start ?? ''} onChange={(e) => setF({ ...f, experience: f.experience.map((x, k) => (k === i ? { ...x, start: e.target.value } : x)) })} />
                    <input className="input" placeholder="Конец" value={j.end ?? ''} onChange={(e) => setF({ ...f, experience: f.experience.map((x, k) => (k === i ? { ...x, end: e.target.value } : x)) })} />
                    <button type="button" className="btn-ghost px-2" onClick={() => setF({ ...f, experience: f.experience.filter((_, k) => k !== i) })} aria-label="Удалить">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    <select className="input" aria-label="Роль на этом месте" value={j.specialization ?? ''} onChange={(e) => setF({ ...f, experience: f.experience.map((x, k) => (k === i ? { ...x, specialization: e.target.value || null } : x)) })}>
                      <option value="">Роль: не IT / другое</option>
                      {cat?.specializations.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.title}
                        </option>
                      ))}
                    </select>
                    <select className="input" aria-label="Отрасль компании" value={j.industry ?? ''} onChange={(e) => setF({ ...f, experience: f.experience.map((x, k) => (k === i ? { ...x, industry: e.target.value || null } : x)) })}>
                      <option value="">Отрасль не указана</option>
                      {cat?.industries.map((x) => (
                        <option key={x.id} value={x.id}>
                          {x.title}
                        </option>
                      ))}
                    </select>
                  </div>
                  <textarea className="input mt-2 min-h-14" placeholder="Задачи и стек" value={j.description ?? ''} onChange={(e) => setF({ ...f, experience: f.experience.map((x, k) => (k === i ? { ...x, description: e.target.value } : x)) })} />
                </div>
              ))}
            </div>
          </Section>
          <ErrorBox error={save.error} />
          <div className="sticky bottom-4 flex items-center gap-3">
            <button className="btn-primary px-6 shadow-lg" disabled={save.isPending}>
              Сохранить профиль
            </button>
            {saved && <span className="text-sm text-ok-600">Сохранено</span>}
          </div>
        </form>

        <aside className="space-y-6">
          <Section title="Резюме из PDF">
            <p className="text-sm text-muted">Распознаём ФИО, контакты, стек, стаж, роли и софт-скиллы. Ничего не сохраняется в профиль без вашего подтверждения.</p>
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) upload.mutate(file)
                e.target.value = ''
              }}
            />
            <button className="btn-secondary mt-4 w-full" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
              <FileUp className="h-4 w-4" /> {upload.isPending ? 'Распознаём…' : 'Загрузить PDF'}
            </button>
            <div className="mt-3">
              <ErrorBox error={upload.error} />
            </div>
            {parsed && (
              <div className="mt-4 space-y-3 text-sm">
                {parsed.warnings.map((w) => (
                  <Notice key={w} tone="warn">
                    {w}
                  </Notice>
                ))}
                <dl className="grid grid-cols-[6rem_1fr] gap-x-2 gap-y-1">
                  <dt className="text-muted">ФИО</dt>
                  <dd>{parsed.suggestions.full_name ?? '—'}</dd>
                  <dt className="text-muted">Контакты</dt>
                  <dd className="break-all">{[parsed.suggestions.contact_email, parsed.suggestions.phone, parsed.suggestions.telegram].filter(Boolean).join(', ') || '—'}</dd>
                  <dt className="text-muted">Должность</dt>
                  <dd>{parsed.suggestions.headline ?? '—'}</dd>
                  <dt className="text-muted">Стаж в IT</dt>
                  <dd>{String(parsed.suggestions.experience_years).replace('.', ',')} г.</dd>
                  <dt className="text-muted">Опыт</dt>
                  <dd>
                    {parsed.suggestions.experience.length ? (
                      <ul className="space-y-0.5">
                        {parsed.suggestions.experience.map((j, i) => (
                          <li key={i}>
                            {j.title} <span className="text-muted">· {j.start} — {j.end}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      '—'
                    )}
                  </dd>
                  <dt className="text-muted">Грейд</dt>
                  <dd>
                    {parsed.suggestions.claimed_grade ?? '—'} <span className="text-muted">({parsed.suggestions.grade_reason})</span>
                  </dd>
                  <dt className="text-muted">Стек</dt>
                  <dd>{parsed.suggestions.stack.join(', ') || '—'}</dd>
                </dl>
                <button className="btn-primary w-full" onClick={applySuggestions}>
                  <Wand2 className="h-4 w-4" /> Заполнить форму
                </button>
                <p className="hint">Стек, специализацию и грейд подставим в опрос — проверьте их там.</p>
                <Link to="/candidate/survey" className="link text-sm">
                  Перейти к опросу →
                </Link>
              </div>
            )}
          </Section>
        </aside>
      </div>
    </div>
  )
}
