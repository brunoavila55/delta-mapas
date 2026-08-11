import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { MapJobStatus } from '../lib/types'

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span className="block h-0 w-0 border-x-[13px] border-b-[36px] border-x-transparent border-b-emerald-500" />
      {!compact && (
        <span>
          <span className="block text-lg font-black tracking-[0.08em] text-slate-950">DELTA MAPAS</span>
          <span className="block text-[10px] font-medium tracking-wide text-slate-500">Inteligência para o campo</span>
        </span>
      )}
    </div>
  )
}

export function Button({ className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-xl bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
      {...props}
    />
  )
}

export function PageHeader({ eyebrow, title, action }: { eyebrow: string; title: string; action?: ReactNode }) {
  return (
    <header className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.22em] text-emerald-700">{eyebrow}</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-950">{title}</h1>
      </div>
      {action}
    </header>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-slate-200 bg-white shadow-sm ${className}`}>{children}</section>
}

export function LoadingState({ label = 'Carregando…' }: { label?: string }) {
  return (
    <div className="flex min-h-40 items-center justify-center gap-3 text-sm text-slate-500">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-emerald-200 border-t-emerald-700" />
      {label}
    </div>
  )
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center px-6 text-center">
      <span className="mb-4 grid h-12 w-12 place-items-center rounded-full bg-emerald-50 text-xl text-emerald-700">◇</span>
      <p className="font-semibold text-slate-800">{title}</p>
      <p className="mt-1 max-w-sm text-sm text-slate-500">{description}</p>
    </div>
  )
}

const statusStyles: Record<MapJobStatus, string> = {
  PENDING: 'bg-slate-100 text-slate-700',
  SEARCHING_SCENE: 'bg-sky-100 text-sky-800',
  DOWNLOADING: 'bg-cyan-100 text-cyan-800',
  PREPROCESSING: 'bg-indigo-100 text-indigo-800',
  PROCESSING: 'bg-violet-100 text-violet-800',
  RENDERING: 'bg-amber-100 text-amber-800',
  UPLOADING: 'bg-orange-100 text-orange-800',
  COMPLETED: 'bg-emerald-100 text-emerald-800',
  FAILED: 'bg-rose-100 text-rose-800',
  CANCELLED: 'bg-slate-200 text-slate-700',
}

const statusLabels: Record<MapJobStatus, string> = {
  PENDING: 'Pendente',
  SEARCHING_SCENE: 'Buscando cena',
  DOWNLOADING: 'Baixando',
  PREPROCESSING: 'Preparando',
  PROCESSING: 'Processando',
  RENDERING: 'Renderizando',
  UPLOADING: 'Enviando',
  COMPLETED: 'Concluído',
  FAILED: 'Falhou',
  CANCELLED: 'Cancelado',
}

export function StatusBadge({ status }: { status: MapJobStatus }) {
  return <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${statusStyles[status]}`}>{statusLabels[status]}</span>
}
