import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

type ToastKind = 'success' | 'error' | 'info'
type ToastInput = { title: string; message?: string; kind?: ToastKind }
type Toast = ToastInput & { id: number }

const ToastContext = createContext<{ notify: (toast: ToastInput) => void } | null>(null)
let nextToastId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const notify = useCallback((input: ToastInput) => {
    const toast = { ...input, kind: input.kind ?? 'info', id: nextToastId++ }
    setToasts((current) => [...current.slice(-3), toast])
    window.setTimeout(() => dismiss(toast.id), 4_500)
  }, [dismiss])

  useEffect(() => {
    function handleApiError(event: Event) {
      const detail = (event as CustomEvent<{ message?: string }>).detail
      notify({ title: 'Serviço indisponível', message: detail?.message ?? 'Tente novamente em instantes.', kind: 'error' })
    }
    function handleAuthExpired() {
      notify({ title: 'Sessão expirada', message: 'Entre novamente para continuar.', kind: 'info' })
    }
    window.addEventListener('delta-api-error', handleApiError)
    window.addEventListener('delta-auth-expired', handleAuthExpired)
    return () => {
      window.removeEventListener('delta-api-error', handleApiError)
      window.removeEventListener('delta-auth-expired', handleAuthExpired)
    }
  }, [notify])

  const value = useMemo(() => ({ notify }), [notify])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[100] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-3" aria-live="polite" aria-atomic="false">
        {toasts.map((toast) => (
          <div key={toast.id} role={toast.kind === 'error' ? 'alert' : 'status'} className={`pointer-events-auto rounded-2xl border bg-white p-4 shadow-xl ${toast.kind === 'success' ? 'border-emerald-200' : toast.kind === 'error' ? 'border-rose-200' : 'border-sky-200'}`}>
            <div className="flex items-start gap-3">
              <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-sm font-black ${toast.kind === 'success' ? 'bg-emerald-100 text-emerald-700' : toast.kind === 'error' ? 'bg-rose-100 text-rose-700' : 'bg-sky-100 text-sky-700'}`}>
                {toast.kind === 'success' ? '✓' : toast.kind === 'error' ? '!' : 'i'}
              </span>
              <div className="min-w-0 flex-1"><p className="text-sm font-bold text-slate-950">{toast.title}</p>{toast.message && <p className="mt-1 text-xs leading-5 text-slate-600">{toast.message}</p>}</div>
              <button type="button" onClick={() => dismiss(toast.id)} className="text-lg leading-none text-slate-400 hover:text-slate-700" aria-label="Fechar notificação">×</button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast deve ser usado dentro de ToastProvider.')
  return context
}
