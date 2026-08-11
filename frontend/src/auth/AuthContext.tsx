import { useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, tokenStore } from '../lib/api'
import type { LoginResponse, Session } from '../lib/types'

type AuthContextValue = {
  session: Session | null
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [isLoading, setIsLoading] = useState(Boolean(tokenStore.get()))
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!tokenStore.get()) {
      setIsLoading(false)
      return
    }
    api
      .get<Session>('/auth/me/')
      .then(setSession)
      .catch(() => tokenStore.clear())
      .finally(() => setIsLoading(false))
  }, [])

  useEffect(() => {
    function handleExpiredSession() {
      setSession(null)
      queryClient.clear()
    }
    window.addEventListener('delta-auth-expired', handleExpiredSession)
    return () => window.removeEventListener('delta-auth-expired', handleExpiredSession)
  }, [queryClient])

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isLoading,
      async login(username, password) {
        const response = await api.post<LoginResponse>(
          '/auth/login/',
          { username, password },
          undefined,
          false,
        )
        tokenStore.set({ access: response.access, refresh: response.refresh })
        setSession({ user: response.user, tenant: response.tenant })
      },
      async logout() {
        const refresh = tokenStore.get()?.refresh
        try {
          if (refresh) await api.post('/auth/logout/', { refresh })
        } finally {
          tokenStore.clear()
          setSession(null)
          queryClient.clear()
        }
      },
    }),
    [isLoading, queryClient, session],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth deve ser usado dentro de AuthProvider.')
  return context
}
