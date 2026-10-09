import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, BadgeCheck, Download, Lock, Medal, ScanFace, Send, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { FspList, InviteModal, SkillList } from '../../components/domain'
import { Badge, Notice, PageHeader, PageLoader, Section } from '../../components/ui'
import { api } from '../../lib/api'
import { date, experienceText, lookup, pct, useCatalog } from '../../lib/catalog'
import type { CandidateCard } from '../../lib/types'

/** Кадр с теста с проктором: работодатель сверяет лицо на собеседовании (после принятого приглашения). */
function TestPhoto({ id }: { id: string }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let u: string | null = null
    api.blob(`/api/employer/candidates/${id}/test-photo`).then((b) => setUrl((u = URL.createObjectURL(b))), () => setUrl(null))
    return () => {
      if (u) URL.revokeObjectURL(u)
    }
  }, [id])
  if (!url) return null
  return (
    <div className="mt-4 flex items-start gap-3 rounded-xl border border-line p-3">
      <img src={url} alt="Кадр кандидата с проверки перед тестом" className="h-24 w-32 shrink-0 rounded-lg object-cover" />
      <div className="text-xs text-muted">
        <div className="flex items-center gap-1.5 text-sm font-medium text-ink">
          <ScanFace className="h-4 w-4" /> Кадр с теста
        </div>
        Сверьте на собеседовании, что тест проходил этот же человек.
      </div>
    </div>
  )
}

function ProctorBadges({ c }: { c: CandidateCard }) {
  const pr = c.assessment?.proctoring
  const pace = c.assessment?.pace
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {pr?.status === 'verified' && (
        <Badge tone="bg-ok-50 text-ok-600">
          <ShieldCheck className="mr-1 inline h-3.5 w-3.5" />
          Тест с проктором{pr.identity === 'match' ? ' · лицо совпало с эталоном' : ''}
        </Badge>
      )}
      {pr?.status === 'interrupted' && <Badge tone="bg-surface text-muted">Проктор прерывался</Badge>}
      {c.confirmed_at && (!pr || pr.status === 'off') && <Badge tone="bg-surface text-muted">Тест без проктора</Badge>}
      {!!pace?.overtime_items && (
        <Badge tone="bg-surface text-ink-soft">
          С превышением времени: {pace.overtime_items} из {pace.items} заданий
        </Badge>
      )}
      {c.fsp_linked && (
        <Badge tone="bg-brand-50 text-brand-700">
          <BadgeCheck className="mr-1 inline h-3.5 w-3.5" />
          Личность подтверждена · ФСП ID
        </Badge>
      )}
    </div>
  )
}

export default function CandidateView() {
  const { id } = useParams()
  const { data: cat } = useCatalog()
  const L = lookup(cat)
  const [invite, setInvite] = useState(false)
  const card = useQuery({ queryKey: ['candidate', id], queryFn: () => api.get<CandidateCard>(`/api/employer/candidates/${id}`) })
  const c = card.data
  if (!c) return <PageLoader queries={[card]} />
  return (
    <div>
      <PageHeader
        title={c.revealed && c.full_name ? c.full_name : c.alias}
        subtitle={[c.headline, c.city, experienceText(c)].filter(Boolean).join(' · ')}
        actions={
          <>
            <button className="btn-secondary" onClick={() => api.download(`/api/employer/candidates/${c.id}/profile.pdf`, 'candidate.pdf')}>
              <Download className="h-4 w-4" /> PDF
            </button>
            {!c.revealed && (
              <button className="btn-primary" onClick={() => setInvite(true)}>
                <Send className="h-4 w-4" /> Пригласить
              </button>
            )}
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          <Section title="Категория и результат теста">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="bg-brand-500 text-white">{c.category}</Badge>
              <span className="text-sm text-muted">подтверждено {date(c.confirmed_at)}</span>
            </div>
            <ProctorBadges c={c} />
            {c.test_photo_available && <TestPhoto id={c.id} />}
            <div className="mt-4 grid grid-cols-2 gap-3 text-center">
              <div className="rounded-xl bg-surface p-3">
                <div className="font-mono text-xl font-bold">{pct(c.test_percentile)}</div>
                <div className="text-[11px] text-muted">перцентиль в категории</div>
              </div>
              <div className="rounded-xl bg-surface p-3">
                <div className="font-mono text-xl font-bold">{c.last_active_days ?? '—'}</div>
                <div className="text-[11px] text-muted">дн. с последней активности</div>
              </div>
            </div>
            {c.assessment && (
              <div className="mt-4 space-y-2 text-sm">
                {c.assessment.scenario && (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-muted">Практический кейс «{c.assessment.scenario.title}»:</span>
                    <Badge tone={c.assessment.scenario.category >= 2 ? 'bg-ok-50 text-ok-600' : 'bg-warn-50 text-warn-600'}>{c.assessment.scenario.category_title}</Badge>
                  </div>
                )}
                {c.assessment.integrity.level === 'clean' ? (
                  <p className="flex items-center gap-1.5 text-ok-600">
                    <ShieldCheck className="h-4 w-4" /> Тест пройден без замечаний.
                  </p>
                ) : (
                  <Notice tone="warn">
                    <span className="flex items-start gap-2">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>
                        <b>Замечания к прохождению теста:</b> {c.assessment.integrity.reasons.join('; ')}. Рекомендуем уточнить уровень на интервью.
                      </span>
                    </span>
                  </Notice>
                )}
              </div>
            )}
            <div className="mt-5">
              <SkillList scores={c.skill_scores} />
            </div>
          </Section>
          <Section title="Стек (заявлено кандидатом)">
            <div className="flex flex-wrap gap-1.5">
              {c.stack.map((s) => (
                <Badge key={s}>{s}</Badge>
              ))}
            </div>
          </Section>
          {c.about && (
            <Section title="О себе">
              <p className="text-sm whitespace-pre-wrap text-ink-soft">{c.about}</p>
            </Section>
          )}
        </div>
        <div className="space-y-6">
          <Section title="Контакты">
            {c.revealed && c.contacts ? (
              <dl className="grid grid-cols-[6rem_1fr] gap-y-1.5 text-sm">
                {Object.entries(c.contacts).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted">{k}</dt>
                    <dd className="font-mono break-all">{v}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <div className="flex gap-3 text-sm text-muted">
                <Lock className="h-5 w-5 shrink-0 text-steel" />
                ФИО и контакты откроются, когда кандидат примет ваше приглашение или откликнется на вашу вакансию.
              </div>
            )}
          </Section>
          <Section
            title={
              <span className="flex items-center gap-2">
                <Medal className="h-4 w-4 text-accent-500" /> Достижения ФСП
              </span>
            }
          >
            <FspList items={c.fsp} linked={c.fsp_linked} visible={c.fsp_visible} />
          </Section>
          <Section title="Условия">
            <div className="text-sm text-ink-soft">Формат: {c.work_formats.map(L.format).join(', ') || '—'}</div>
            <div className="mt-2">
              <p className="hint">Ожидания скрыты; совпадение вилки покажем в приглашении.</p>
            </div>
          </Section>
        </div>
      </div>
      {invite && <InviteModal open candidate={{ id: c.id, label: c.alias }} onClose={() => setInvite(false)} />}
    </div>
  )
}
