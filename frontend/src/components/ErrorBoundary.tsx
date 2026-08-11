import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Logo } from './ui'

type Props = { children: ReactNode }
type State = { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Erro não tratado na interface', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="grid min-h-screen place-items-center bg-[#f5f7f4] p-6">
        <section className="w-full max-w-lg rounded-3xl border border-rose-200 bg-white p-8 text-center shadow-xl">
          <div className="flex justify-center"><Logo /></div>
          <p className="mt-8 text-xs font-bold uppercase tracking-[0.2em] text-rose-700">Falha inesperada</p>
          <h1 className="mt-2 text-2xl font-bold text-slate-950">A interface não conseguiu continuar.</h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">Seus dados não foram alterados. Recarregue a página para recuperar a sessão.</p>
          <button type="button" onClick={() => window.location.reload()} className="mt-6 rounded-xl bg-emerald-700 px-5 py-3 text-sm font-bold text-white hover:bg-emerald-800">Recarregar aplicação</button>
        </section>
      </main>
    )
  }
}
