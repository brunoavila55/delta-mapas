type Tokens = { access: string; refresh: string }

const TOKEN_KEY = 'delta-mapas.session'

export class ApiError extends Error {
  status: number
  data: unknown

  constructor(message: string, status: number, data: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

function errorMessage(data: unknown): string {
  if (typeof data === 'string') return data
  if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>
    if (typeof record.detail === 'string') return record.detail
    const first = Object.values(record)[0]
    if (typeof first === 'string') return first
    if (Array.isArray(first) && typeof first[0] === 'string') return first[0]
  }
  return 'Não foi possível concluir a solicitação.'
}

export const tokenStore = {
  get(): Tokens | null {
    try {
      const stored = sessionStorage.getItem(TOKEN_KEY)
      return stored ? (JSON.parse(stored) as Tokens) : null
    } catch {
      return null
    }
  },
  set(tokens: Tokens) {
    sessionStorage.setItem(TOKEN_KEY, JSON.stringify(tokens))
  },
  clear() {
    sessionStorage.removeItem(TOKEN_KEY)
  },
}

let refreshPromise: Promise<string> | null = null

async function fetchSafe(input: RequestInfo | URL, init?: RequestInit) {
  try {
    return await fetch(input, init)
  } catch (error) {
    const message = 'Não foi possível conectar ao servidor.'
    window.dispatchEvent(new CustomEvent('delta-api-error', { detail: { message } }))
    throw new ApiError(message, 0, error)
  }
}

function expireSession() {
  tokenStore.clear()
  window.dispatchEvent(new Event('delta-auth-expired'))
}

async function refreshAccessToken(): Promise<string> {
  const tokens = tokenStore.get()
  if (!tokens?.refresh) throw new ApiError('Sessão expirada.', 401, null)
  const response = await fetchSafe('/api/v1/auth/refresh/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: tokens.refresh }),
  })
  const data = (await response.json().catch(() => null)) as
    | { access?: string; refresh?: string }
    | null
  if (!response.ok || !data?.access) {
    expireSession()
    throw new ApiError('Sessão expirada.', response.status, data)
  }
  tokenStore.set({ access: data.access, refresh: data.refresh ?? tokens.refresh })
  return data.access
}

type RequestOptions = RequestInit & { auth?: boolean; retryAuth?: boolean }

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { auth = true, retryAuth = true, ...fetchOptions } = options
  const headers = new Headers(fetchOptions.headers)
  const tokens = tokenStore.get()
  if (auth && tokens?.access) headers.set('Authorization', `Bearer ${tokens.access}`)
  if (fetchOptions.body && !(fetchOptions.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetchSafe(path.startsWith('http') ? path : `/api/v1${path}`, {
    ...fetchOptions,
    headers,
  })
  if (response.status === 401 && auth && retryAuth && tokens?.refresh) {
    refreshPromise ??= refreshAccessToken().finally(() => {
      refreshPromise = null
    })
    await refreshPromise
    return request<T>(path, { ...options, retryAuth: false })
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    if (response.status >= 500) window.dispatchEvent(new CustomEvent('delta-api-error', { detail: { message: errorMessage(data) } }))
    throw new ApiError(errorMessage(data), response.status, data)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  get<T>(path: string) {
    return request<T>(path)
  },
  post<T>(path: string, data?: unknown, headers?: HeadersInit, auth = true) {
    return request<T>(path, {
      method: 'POST',
      body: data === undefined ? undefined : JSON.stringify(data),
      headers,
      auth,
    })
  },
  postForm<T>(path: string, data: FormData) {
    return request<T>(path, { method: 'POST', body: data })
  },
  patch<T>(path: string, data: unknown) {
    return request<T>(path, { method: 'PATCH', body: JSON.stringify(data) })
  },
  delete(path: string) {
    return request<void>(path, { method: 'DELETE' })
  },
  async download(path: string): Promise<Blob> {
    const tokens = tokenStore.get()
    let response = await fetchSafe(path, {
      headers: tokens?.access ? { Authorization: `Bearer ${tokens.access}` } : {},
    })
    if (response.status === 401 && tokens?.refresh) {
      refreshPromise ??= refreshAccessToken().finally(() => {
        refreshPromise = null
      })
      const access = await refreshPromise
      response = await fetchSafe(path, { headers: { Authorization: `Bearer ${access}` } })
    }
    if (!response.ok) throw new ApiError('Não foi possível baixar o arquivo.', response.status, null)
    return response.blob()
  },
}
