import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Catalog } from './types'

export function useCatalog() {
  return useQuery({ queryKey: ['catalog'], queryFn: () => api.get<Catalog>('/api/catalog'), staleTime: Infinity })
}

export function lookup(cat: Catalog | undefined) {
  return {
    grade: (id?: string | null) => cat?.grades.find((g) => g.id === id)?.name ?? id ?? '—',
    gradeTitle: (id?: string | null) => cat?.grades.find((g) => g.id === id)?.title ?? '',
    spec: (id?: string | null) => cat?.specializations.find((s) => s.id === id)?.name ?? id ?? '—',
    specTitle: (id?: string | null) => cat?.specializations.find((s) => s.id === id)?.title ?? id ?? '—',
    skill: (id?: string | null) => cat?.assessment_skills.find((s) => s.id === id)?.title ?? id ?? '—',
    industry: (id?: string | null) => cat?.industries.find((s) => s.id === id)?.title ?? id ?? '—',
    format: (id?: string | null) => cat?.work_formats.find((s) => s.id === id)?.title ?? id ?? '—',
    reason: (id?: string | null) => cat?.decline_reasons.find((s) => s.id === id)?.title ?? id ?? '—',
    fspResult: (id?: string | null) => cat?.fsp.results.find((s) => s.id === id)?.title ?? id ?? '',
    fspLevel: (id?: string | null) => cat?.fsp.levels.find((s) => s.id === id)?.title ?? id ?? '',
    fspDiscipline: (id?: string | null) => cat?.fsp.disciplines.find((s) => s.id === id)?.title ?? id ?? '',
    fspDisciplineInfo: (id?: string | null) => cat?.fsp.disciplines.find((s) => s.id === id),
  }
}

export const money = (n?: number | null) => (n == null ? '—' : `${Math.round(n).toLocaleString('ru-RU')} ₽`)

export const range = (a?: number | null, b?: number | null) => {
  if (a && b) return `${Math.round(a / 1000).toLocaleString('ru-RU')}–${Math.round(b / 1000).toLocaleString('ru-RU')} тыс. ₽`
  if (a) return `от ${Math.round(a / 1000).toLocaleString('ru-RU')} тыс. ₽`
  if (b) return `до ${Math.round(b / 1000).toLocaleString('ru-RU')} тыс. ₽`
  return 'не указана'
}

export const date = (s?: string | null) => (s ? new Date(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }) : '—')

export const dateTime = (s?: string | null) =>
  s ? new Date(s).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'

export const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}

export const pct = (x?: number | null) => (x == null ? '—' : `${Math.round(x * 100)}%`)

export const INVITE_STATUS: Record<string, { label: string; tone: string }> = {
  sent: { label: 'Отправлено', tone: 'bg-brand-50 text-brand-700' },
  viewed: { label: 'Просмотрено', tone: 'bg-warn-50 text-warn-600' },
  accepted: { label: 'Принято', tone: 'bg-ok-50 text-ok-600' },
  declined: { label: 'Отклонено', tone: 'bg-accent-50 text-accent-600' },
  withdrawn: { label: 'Отозвано', tone: 'bg-surface text-muted' },
  hired: { label: 'Вышел на работу', tone: 'bg-ok-50 text-ok-600' },
}

export const APP_STATUS: Record<string, { label: string; tone: string }> = {
  sent: { label: 'Отправлен', tone: 'bg-brand-50 text-brand-700' },
  viewed: { label: 'Просмотрен', tone: 'bg-warn-50 text-warn-600' },
  interview: { label: 'Приглашение на интервью', tone: 'bg-ok-50 text-ok-600' },
  rejected: { label: 'Отказ', tone: 'bg-accent-50 text-accent-600' },
  hired: { label: 'Оффер', tone: 'bg-ok-50 text-ok-600' },
}

export const SALARY_FIT: Record<string, { label: string; tone: string }> = {
  within: { label: 'Вилка в ожиданиях', tone: 'bg-ok-50 text-ok-600' },
  above: { label: 'Вилка выше ожиданий', tone: 'bg-ok-50 text-ok-600' },
  partial: { label: 'Вилка частично подходит', tone: 'bg-warn-50 text-warn-600' },
  below: { label: 'Вилка ниже ожиданий', tone: 'bg-accent-50 text-accent-600' },
  unknown: { label: 'Ожидания не указаны', tone: 'bg-surface text-muted' },
}

export const SKILL_STATUS: Record<string, { label: string; tone: string; dot: string }> = {
  confirmed: { label: 'подтверждено', tone: 'bg-ok-50 text-ok-600', dot: 'bg-ok-600' },
  uncertain: { label: 'частично', tone: 'bg-warn-50 text-warn-600', dot: 'bg-warn-600' },
  weak: { label: 'не подтверждено', tone: 'bg-accent-50 text-accent-600', dot: 'bg-accent-500' },
  no_data: { label: 'нет данных', tone: 'bg-surface text-muted', dot: 'bg-steel' },
}

const yrs = (y: number) => (y < 1 ? (y > 0 ? 'меньше года' : '0') : `${String(Math.round(y * 10) / 10).replace('.', ',')} г.`)

/** «опыт 6 г., в роли 2 г.» — общий и релевантный стаж кандидата. */
export function experienceText(c: { experience_years: number | null; relevant_years?: number | null }): string | null {
  if (c.experience_years == null && c.relevant_years == null) return null
  if (!c.experience_years && !c.relevant_years) return 'без опыта работы'
  const total = c.experience_years ?? c.relevant_years ?? 0
  if (c.relevant_years == null || Math.abs(total - c.relevant_years) < 0.4) return `опыт ${yrs(total)}`
  return `опыт ${yrs(total)}, в роли ${yrs(c.relevant_years)}`
}
