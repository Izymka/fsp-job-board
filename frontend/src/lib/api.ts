// Тонкий клиент API: токен, единый формат ошибок {error: {code, message, details}}.

export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

let tokenProvider: () => Promise<string | null> = async () => null

export function setTokenProvider(fn: () => Promise<string | null>) {
  tokenProvider = fn
}

async function request<T>(method: string, url: string, body?: unknown, opts: { raw?: boolean; form?: FormData } = {}): Promise<T> {
  const token = await tokenProvider()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  let payload: BodyInit | undefined
  if (opts.form) payload = opts.form
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(url, { method, headers, body: payload })
  if (opts.raw) {
    if (!res.ok) throw new ApiError(res.status, 'http_error', `Ошибка ${res.status}`)
    return res as unknown as T
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const e = data?.error
    let message = e?.message || `Ошибка ${res.status}`
    if (e?.code === 'validation_error' && Array.isArray(e.details) && e.details.length) {
      message = e.details.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
    }
    throw new ApiError(res.status, e?.code || 'http_error', message, e?.details)
  }
  return data as T
}

export const api = {
  get: <T,>(url: string) => request<T>('GET', url),
  post: <T,>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T,>(url: string, body?: unknown) => request<T>('PUT', url, body ?? {}),
  del: <T,>(url: string) => request<T>('DELETE', url),
  upload: <T,>(url: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<T>('POST', url, undefined, { form })
  },
  async blob(url: string): Promise<Blob> {
    const res = await request<Response>('GET', url, undefined, { raw: true })
    return res.blob()
  },
  async download(url: string, filename: string) {
    const res = await request<Response>('GET', url, undefined, { raw: true })
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = filename
    a.click()
    URL.revokeObjectURL(a.href)
  },
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return 'Что-то пошло не так'
}
