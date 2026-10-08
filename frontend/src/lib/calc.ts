// Калькулятор черновика теста: разбор выражения без eval.
// Грамматика: expr = term (('+'|'-') term)*; term = unary (('*'|'/'|'mod') unary)*;
// unary = '-' unary | power; power = postfix ('^' unary)?; postfix = atom '%'*  (−2^2 = −4, 2^−1 = 0.5);
// atom = число | константа | функция '(' expr ')' | '(' expr ')'.

const FUNCS: Record<string, (x: number) => number> = {
  sqrt: Math.sqrt,
  '√': Math.sqrt,
  ln: Math.log,
  log: Math.log10,
  log10: Math.log10,
  log2: Math.log2,
  abs: Math.abs,
  round: Math.round,
  floor: Math.floor,
  ceil: Math.ceil,
}
const CONSTS: Record<string, number> = { pi: Math.PI, 'π': Math.PI, e: Math.E }

type Tok = { t: 'num'; v: number } | { t: 'id'; v: string } | { t: 'op'; v: string }

function tokenize(src: string): Tok[] {
  const s = src.replace(/×/g, '*').replace(/÷/g, '/').replace(/−/g, '-').replace(/,/g, '.')
  const out: Tok[] = []
  let i = 0
  while (i < s.length) {
    const c = s[i]
    if (/\s/.test(c)) {
      i++
    } else if (/[0-9.]/.test(c)) {
      const m = /^(\d+\.?\d*|\.\d+)(e[+-]?\d+)?/i.exec(s.slice(i))
      if (!m) throw new Error('Неверное число')
      out.push({ t: 'num', v: parseFloat(m[0]) })
      i += m[0].length
    } else if (/[a-zа-яπ√]/i.test(c)) {
      const m = /^([a-z]+\d*|π|√)/i.exec(s.slice(i))
      if (!m) throw new Error(`Неизвестный символ «${c}»`)
      out.push({ t: 'id', v: m[0].toLowerCase() })
      i += m[0].length
    } else if ('+-*/^()%'.includes(c)) {
      out.push({ t: 'op', v: c })
      i++
    } else throw new Error(`Неизвестный символ «${c}»`)
  }
  return out
}

export function evaluate(src: string): number {
  const toks = tokenize(src)
  let p = 0
  const peek = () => toks[p]
  const isOp = (v: string) => peek()?.t === 'op' && peek()!.v === v
  const expect = (v: string) => {
    if (!isOp(v)) throw new Error(`Ожидалось «${v}»`)
    p++
  }
  const expr = (): number => {
    let x = term()
    for (;;) {
      if (isOp('+')) (p++, (x += term()))
      else if (isOp('-')) (p++, (x -= term()))
      else return x
    }
  }
  const term = (): number => {
    let x = unary()
    for (;;) {
      if (isOp('*')) (p++, (x *= unary()))
      else if (isOp('/')) (p++, (x /= unary()))
      else if (peek()?.t === 'id' && peek()!.v === 'mod') (p++, (x %= unary()))
      else return x
    }
  }
  const unary = (): number => {
    if (isOp('-')) return p++, -unary()
    if (isOp('+')) return p++, unary()
    return power()
  }
  const power = (): number => {
    const b = postfix()
    if (isOp('^')) {
      p++
      return b ** unary()
    }
    return b
  }
  const postfix = (): number => {
    let x = atom()
    while (isOp('%')) (p++, (x /= 100))
    return x
  }
  const atom = (): number => {
    const tk = toks[p++]
    if (!tk) throw new Error('Выражение не закончено')
    if (tk.t === 'num') return tk.v
    if (tk.t === 'op' && tk.v === '(') {
      const x = expr()
      expect(')')
      return x
    }
    if (tk.t === 'id') {
      if (tk.v in CONSTS) return CONSTS[tk.v]
      const f = FUNCS[tk.v]
      if (!f) throw new Error(`Неизвестная функция «${tk.v}»`)
      if (isOp('(')) {
        p++
        const x = expr()
        expect(')')
        return f(x)
      }
      return f(unary()) // √2, sqrt 9
    }
    throw new Error(`Неожиданный символ «${tk.v}»`)
  }
  const v = expr()
  if (p < toks.length) throw new Error('Лишние символы в выражении')
  if (!Number.isFinite(v)) throw new Error('Результат не определён')
  return v
}

export function formatResult(v: number): string {
  return Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(12))).replace('.', ',')
}
