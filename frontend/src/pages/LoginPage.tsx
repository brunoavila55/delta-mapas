import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Button, Logo } from '../components/ui'
import { errorText } from '../lib/format'

export function LoginPage() {
  const { session, login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  if (session) return <Navigate to="/" replace />

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await login(username, password)
      const target = (location.state as { from?: string } | null)?.from ?? '/'
      navigate(target, { replace: true })
    } catch (requestError) {
      setError(errorText(requestError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="grid min-h-screen bg-[#eef2ed] lg:grid-cols-[1.1fr_0.9fr]">
      <section className="relative hidden overflow-hidden bg-emerald-950 p-14 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute inset-0 opacity-30 [background-image:radial-gradient(circle_at_20%_30%,#4ade80_0,transparent_28%),radial-gradient(circle_at_80%_75%,#fbbf24_0,transparent_24%)]" />
        <div className="relative"><Logo /></div>
        <div className="relative max-w-xl">
          <p className="text-sm font-bold uppercase tracking-[0.28em] text-emerald-300">Sensoriamento remoto agrícola</p>
          <h1 className="mt-6 text-5xl font-bold leading-tight">Decisões melhores começam com uma visão mais clara do campo.</h1>
          <p className="mt-6 max-w-lg text-lg leading-8 text-emerald-100/75">Transforme imagens Sentinel-2 em mapas NDVI rastreáveis, cartográficos e prontos para compartilhar.</p>
        </div>
        <p className="relative text-xs text-emerald-200/60">Copernicus Data Space · Sentinel-2 L2A</p>
      </section>

      <section className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md rounded-3xl border border-white/60 bg-white p-7 shadow-2xl shadow-emerald-950/10 sm:p-10">
          <div className="mb-10 lg:hidden"><Logo /></div>
          <p className="text-xs font-bold uppercase tracking-[0.22em] text-emerald-700">Área do cliente</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-slate-950">Entre na sua organização</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">Use suas credenciais para acessar propriedades, processamentos e mapas.</p>
          <form className="mt-8 space-y-5" onSubmit={submit}>
            <label className="block text-sm font-semibold text-slate-700">
              Usuário
              <input autoFocus autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3 outline-none transition focus:border-emerald-600 focus:ring-4 focus:ring-emerald-100" required />
            </label>
            <label className="block text-sm font-semibold text-slate-700">
              Senha
              <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3 outline-none transition focus:border-emerald-600 focus:ring-4 focus:ring-emerald-100" required />
            </label>
            {error && <p role="alert" className="rounded-xl bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">{error}</p>}
            <Button className="w-full py-3" disabled={submitting}>{submitting ? 'Entrando…' : 'Entrar'}</Button>
          </form>
        </div>
      </section>
    </main>
  )
}
