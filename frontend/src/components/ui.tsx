import clsx from 'clsx'
import { AlertCircle, Loader2, X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx('animate-spin text-brand-500', className ?? 'h-5 w-5')} aria-label="Загрузка" />
}

export function PageLoader() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <Spinner className="h-7 w-7" />
    </div>
  )
}

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && <div className="mb-1 font-mono text-xs tracking-wider text-brand-500 uppercase">{eyebrow}</div>}
        <h1 className="text-2xl font-bold sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-3xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export function Badge({ children, tone = 'bg-surface text-ink-soft', className }: { children: ReactNode; tone?: string; className?: string }) {
  return <span className={clsx('chip', tone, className)}>{children}</span>
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <div className="flex items-start gap-2 rounded-lg border border-accent-100 bg-accent-50 px-3 py-2.5 text-sm text-accent-600" role="alert">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{msg}</span>
    </div>
  )
}

export function Notice({ children, tone = 'brand' }: { children: ReactNode; tone?: 'brand' | 'ok' | 'warn' }) {
  const t = { brand: 'border-brand-100 bg-brand-50 text-brand-800', ok: 'border-ok-50 bg-ok-50 text-ok-600', warn: 'border-warn-50 bg-warn-50 text-warn-600' }[tone]
  return <div className={clsx('rounded-lg border px-3 py-2.5 text-sm', t)}>{children}</div>
}

export function EmptyState({ title, text, action, icon }: { title: string; text?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-500">{icon ?? <img src="/brand/mark.svg" alt="" className="h-7 w-7" />}</div>
      <h3 className="text-base font-semibold">{title}</h3>
      {text && <p className="mt-1.5 max-w-md text-sm text-muted">{text}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="card p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 font-mono text-2xl font-bold">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  )
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', h)
      document.body.style.overflow = ''
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 p-0 sm:items-center sm:p-4" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        className={clsx('max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-xl sm:rounded-2xl', wide ? 'sm:max-w-3xl' : 'sm:max-w-lg')}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-white px-5 py-4">
          <h2 className="text-lg font-bold">{title}</h2>
          <button className="btn-ghost -mr-2 p-2" onClick={onClose} aria-label="Закрыть">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}

export function Field({ label, hint, children, required }: { label: ReactNode; hint?: ReactNode; children: ReactNode; required?: boolean }) {
  return (
    <label className="block">
      <span className="label">
        {label}
        {required && <span className="text-accent-500"> *</span>}
      </span>
      {children}
      {hint && <span className="hint block">{hint}</span>}
    </label>
  )
}

export function Section({ title, children, actions, className }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={clsx('card p-5', className)}>
      {(title || actions) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="shrink-0 text-base font-bold">{title}</h2>}
          {actions && <div className="min-w-0 text-right">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: ReactNode }[] }) {
  return (
    <div className="mb-5 flex gap-1 overflow-x-auto rounded-xl bg-surface p-1">
      {items.map((it) => (
        <button
          key={it.id}
          onClick={() => onChange(it.id)}
          className={clsx('rounded-lg px-3.5 py-2 text-sm font-medium whitespace-nowrap transition-colors', value === it.id ? 'bg-white text-ink shadow-sm' : 'text-muted hover:text-ink')}
        >
          {it.label}
        </button>
      ))}
    </div>
  )
}

export function Progress({ value, className, tone = 'bg-brand-500' }: { value: number; className?: string; tone?: string }) {
  return (
    <div className={clsx('h-1.5 w-full overflow-hidden rounded-full bg-fog', className)}>
      <div className={clsx('h-full rounded-full transition-all', tone)} style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} />
    </div>
  )
}

/** Декоративная линия с узлами — мотив брендбука ФСП. */
export function NodeLine({ className }: { className?: string }) {
  return (
    <svg className={clsx('pointer-events-none', className)} viewBox="0 0 400 120" fill="none" aria-hidden>
      <path d="M4 116 V40 Q4 8 36 8 H300 Q340 8 340 48 V70 Q340 110 380 110 H396" stroke="#402FFF" strokeWidth="1.2" />
      <circle cx="4" cy="116" r="3.5" fill="#402FFF" />
      <circle cx="396" cy="110" r="3.5" fill="#402FFF" />
      <circle cx="200" cy="8" r="3" fill="#402FFF" />
    </svg>
  )
}

/** Минимальный безопасный рендер markdown для формулировок заданий: абзацы, **жирный**, `код`, ```блоки```, таблицы, списки. */
export function Md({ text, className }: { text: string; className?: string }) {
  const blocks: ReactNode[] = []
  const lines = text.split('\n')
  let i = 0
  let key = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.startsWith('```')) {
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++])
      i++
      blocks.push(<CodeBlock key={key++} code={buf.join('\n')} />)
      continue
    }
    if (line.trim().startsWith('|')) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        const cells = lines[i].trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
        if (!cells.every((c) => /^-+$/.test(c))) rows.push(cells)
        i++
      }
      blocks.push(
        <div key={key++} className="my-3 overflow-x-auto">
          <table className="min-w-full border-collapse font-mono text-xs">
            <thead>
              <tr>{rows[0]?.map((c, j) => <th key={j} className="border border-line bg-surface px-2.5 py-1.5 text-left font-semibold">{c}</th>)}</tr>
            </thead>
            <tbody>
              {rows.slice(1).map((r, ri) => (
                <tr key={ri}>{r.map((c, j) => <td key={j} className="border border-line px-2.5 py-1.5">{c}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }
    if (/^\s*[-•]\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*[-•]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-•]\s+/, ''))
      blocks.push(
        <ul key={key++} className="my-2 list-disc space-y-1 pl-5">
          {items.map((t, j) => <li key={j}>{inline(t)}</li>)}
        </ul>,
      )
      continue
    }
    if (!line.trim()) {
      i++
      continue
    }
    const para: string[] = []
    while (i < lines.length && lines[i].trim() && !lines[i].startsWith('```') && !lines[i].trim().startsWith('|') && !/^\s*[-•]\s+/.test(lines[i])) para.push(lines[i++])
    blocks.push(<p key={key++} className="my-2 leading-relaxed">{inline(para.join(' '))}</p>)
  }
  return <div className={clsx('text-sm text-ink', className)}>{blocks}</div>
}

function inline(s: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g
  let last = 0
  let m: RegExpExecArray | null
  let k = 0
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index))
    const t = m[0]
    if (t.startsWith('**')) out.push(<strong key={k++}>{t.slice(2, -2)}</strong>)
    else if (t.startsWith('`')) out.push(<code key={k++} className="rounded bg-surface px-1 py-0.5 font-mono text-[0.85em]">{t.slice(1, -1)}</code>)
    else out.push(<em key={k++}>{t.slice(1, -1)}</em>)
    last = m.index + t.length
  }
  if (last < s.length) out.push(s.slice(last))
  return out
}

export function CodeBlock({ code, lang }: { code: string; lang?: string | null }) {
  return (
    <div className="my-3 overflow-hidden rounded-xl border border-ink/10 bg-ink">
      {lang && <div className="border-b border-white/10 px-3 py-1.5 font-mono text-[11px] tracking-wider text-steel uppercase">{lang}</div>}
      <pre className="overflow-x-auto p-4 text-[13px] leading-relaxed text-fog">
        <code>{code}</code>
      </pre>
    </div>
  )
}
