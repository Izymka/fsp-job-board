import { X } from 'lucide-react'
import { useMemo, useState } from 'react'

/** Ввод стека с автодополнением из справочника технологий. */
export function TagInput({ value, onChange, suggestions, placeholder }: { value: string[]; onChange: (v: string[]) => void; suggestions: string[]; placeholder?: string }) {
  const [q, setQ] = useState('')
  const [focus, setFocus] = useState(false)
  const matches = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return []
    return suggestions.filter((x) => x.toLowerCase().includes(s) && !value.includes(x)).slice(0, 8)
  }, [q, suggestions, value])
  const add = (t: string) => {
    const v = t.trim()
    if (v && !value.includes(v)) onChange([...value, v])
    setQ('')
  }
  return (
    <div className="relative">
      <div className="input flex min-h-11 flex-wrap items-center gap-1.5 py-1.5">
        {value.map((t) => (
          <span key={t} className="chip bg-brand-50 text-brand-700">
            {t}
            <button type="button" onClick={() => onChange(value.filter((x) => x !== t))} aria-label={`Убрать ${t}`} className="hover:text-accent-600">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          className="min-w-32 flex-1 border-0 bg-transparent p-1 text-sm outline-none"
          value={q}
          placeholder={value.length ? '' : placeholder}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => setFocus(true)}
          onBlur={() => setTimeout(() => setFocus(false), 150)}
          onKeyDown={(e) => {
            if ((e.key === 'Enter' || e.key === ',') && q.trim()) {
              e.preventDefault()
              add(matches[0] ?? q)
            } else if (e.key === 'Backspace' && !q && value.length) {
              onChange(value.slice(0, -1))
            }
          }}
        />
      </div>
      {focus && matches.length > 0 && (
        <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-line bg-white shadow-lg">
          {matches.map((m) => (
            <li key={m}>
              <button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-brand-50" onMouseDown={() => add(m)}>
                {m}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
