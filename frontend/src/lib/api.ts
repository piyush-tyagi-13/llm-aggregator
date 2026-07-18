const BASE = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_BASE || '')

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
      if (!res.ok) {
        const raw = await res.text().catch(() => res.statusText)
        let msg: string
        try {
          const parsed = JSON.parse(raw)
          msg = parsed.detail || parsed.message || parsed.error || raw
        } catch {
          msg = raw
        }
        throw new Error(msg || `${res.status} ${res.statusText}`)
      }
  return res.json()
}
