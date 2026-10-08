// Черновик и калькулятор теста: расчёты без листа бумаги и без сторонних устройств.
// Содержимое не отправляется на сервер; хранится в sessionStorage вкладки до конца попытки.
import clsx from 'clsx'
import { Calculator, ChevronDown, NotebookPen } from 'lucide-react'
import { useEffect, useState } from 'react'
import { evaluate, formatResult } from '../lib/calc'

const key = (attemptId: string) => `scratch:${attemptId}`

function load(attemptId: string): string {
  try {
    return sessionStorage.getItem(key(attemptId)) ?? ''
  } catch {
    return ''
  }
}

export function clearScratch(attemptId: string) {
  try {
    sessionStorage.removeItem(key(attemptId))
  } catch {
    // хранилище недоступно — черновик и так не сохранялся
  }
}

type PasteEvent = { preventDefault: () => void; clipboardData?: DataTransfer | null }

/** Выделенный текст поля ввода (копирование из черновика в ответ разрешено). */
function selected(e: { currentTarget: HTMLInputElement | HTMLTextAreaElement }): string {
  const el = e.currentTarget
  return el.value.slice(el.selectionStart ?? 0, el.selectionEnd ?? 0)
}

/**
 * onPaste — тот же учёт попыток вставки, что и в поле ответа: вставка извне в черновик запрещена.
 * onCopied — что кандидат скопировал из черновика: такую вставку в ответ учёт пропускает.
 */
export function Scratchpad({ attemptId, onPaste, onCopied }: { attemptId: string; onPaste: (e: PasteEvent) => void; onCopied: (text: string) => void }) {
  const [open, setOpen] = useState(false)
  const [notes, setNotes] = useState(() => load(attemptId))
  const [expr, setExpr] = useState('')
  const [history, setHistory] = useState<{ expr: string; result: string }[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    try {
      sessionStorage.setItem(key(attemptId), notes)
    } catch {
      // без хранилища черновик живёт до перезагрузки страницы
    }
  }, [attemptId, notes])

  const calc = () => {
    if (!expr.trim()) return
    try {
      const result = formatResult(evaluate(expr))
      setHistory((h) => [{ expr, result }, ...h].slice(0, 6))
      setExpr(result)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка в выражении')
    }
  }

  return (
    <section className="card mt-4 overflow-hidden">
      <button type="button" className="flex w-full items-center justify-between gap-2 px-5 py-3 text-sm font-medium text-ink-soft" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="flex items-center gap-2">
          <NotebookPen className="h-4 w-4" /> Черновик и калькулятор
        </span>
        <ChevronDown className={clsx('h-4 w-4 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="grid gap-4 border-t border-line px-5 py-4 sm:grid-cols-[1.4fr_1fr]">
          <label className="block">
            <span className="hint">Заметки для себя — работодатель и проверка их не видят</span>
            <textarea className="input mt-1 min-h-40 font-mono text-sm" value={notes} onChange={(e) => setNotes(e.target.value)} onPaste={onPaste} onCopy={(e) => onCopied(selected(e))} onCut={(e) => onCopied(selected(e))} onDrop={(e) => e.preventDefault()} spellCheck={false} />
          </label>
          <div>
            <span className="hint flex items-center gap-1.5">
              <Calculator className="h-3.5 w-3.5" /> + − × ÷ ^ ( ) %, sqrt, log2, ln, mod, pi
            </span>
            <form
              className="mt-1 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                calc()
              }}
            >
              <input className="input font-mono text-sm" value={expr} onChange={(e) => setExpr(e.target.value)} onPaste={onPaste} onCopy={(e) => onCopied(selected(e))} onCut={(e) => onCopied(selected(e))} onDrop={(e) => e.preventDefault()} placeholder="например, 2^10 / 8" inputMode="decimal" aria-label="Выражение" />
              <button className="btn-secondary px-3">=</button>
            </form>
            {error && <p className="mt-1 text-xs text-accent-600">{error}</p>}
            {history.length > 0 && (
              <ul className="mt-2 space-y-0.5 font-mono text-xs text-muted">
                {history.map((h, i) => (
                  <li key={i}>
                    {h.expr} = <span className="text-ink">{h.result}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
