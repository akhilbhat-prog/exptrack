const _STORAGE_KEY = 'exptrack_admin_token'
let _token = sessionStorage.getItem(_STORAGE_KEY) ?? ''

export function setToken(t: string) {
  _token = t
  if (t) sessionStorage.setItem(_STORAGE_KEY, t)
  else sessionStorage.removeItem(_STORAGE_KEY)
}
export function getToken() { return _token }

export function withToken(path: string): string {
  if (!_token) return path
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}token=${encodeURIComponent(_token)}`
}

export class ApiError extends Error {
  status: number
  data?: Record<string, unknown>
  constructor(status: number, message: string, data?: Record<string, unknown>) {
    super(message); this.status = status; this.data = data
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(withToken(path), {
    headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
    credentials: 'include',
    ...options,
  })

  if (res.status === 204) return undefined as T
  if (res.status === 401) {
    window.location.href = '/login'
    throw new ApiError(401, 'Unauthenticated')
  }

  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new ApiError(res.status, data?.error ?? `HTTP ${res.status}`, data)
  }
  return data as T
}

export const api = {
  get:    <T>(path: string) => apiFetch<T>(path),
  post:   <T>(path: string, body?: unknown) =>
            apiFetch<T>(path, { method: 'POST',   body: JSON.stringify(body) }),
  patch:  <T>(path: string, body?: unknown) =>
            apiFetch<T>(path, { method: 'PATCH',  body: JSON.stringify(body) }),
  put:    <T>(path: string, body?: unknown) =>
            apiFetch<T>(path, { method: 'PUT',    body: JSON.stringify(body) }),
  delete: <T>(path: string) =>
            apiFetch<T>(path, { method: 'DELETE' }),
}
