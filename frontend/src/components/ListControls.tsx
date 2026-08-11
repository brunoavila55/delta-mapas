import { errorText } from '../lib/format'

export function SearchInput({ value, onChange, placeholder = 'Buscar…' }: { value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <label className="relative block min-w-0 flex-1 sm:max-w-sm">
      <span aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">⌕</span>
      <span className="sr-only">Buscar</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="w-full rounded-xl border border-slate-300 bg-white py-2.5 pl-9 pr-9 text-sm outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100" />
      {value && <button type="button" onClick={() => onChange('')} aria-label="Limpar busca" className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">×</button>}
    </label>
  )
}

export function Pagination({ page, pageSize, count, onPageChange }: { page: number; pageSize: number; count: number; onPageChange: (page: number) => void }) {
  const totalPages = Math.max(1, Math.ceil(count / pageSize))
  if (totalPages <= 1) return null
  return (
    <nav className="flex flex-col items-center justify-between gap-3 border-t border-slate-100 px-5 py-4 sm:flex-row" aria-label="Paginação">
      <p className="text-xs text-slate-500">Página <strong>{page}</strong> de <strong>{totalPages}</strong> · {count} itens</p>
      <div className="flex gap-2">
        <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-40">← Anterior</button>
        <button type="button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-40">Próxima →</button>
      </div>
    </nav>
  )
}

export function QueryErrorState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center px-6 text-center">
      <span className="grid h-12 w-12 place-items-center rounded-full bg-rose-100 text-xl font-black text-rose-700">!</span>
      <p className="mt-4 font-bold text-slate-900">Não foi possível carregar os dados.</p>
      <p className="mt-1 max-w-md text-sm text-slate-500">{errorText(error)}</p>
      <button type="button" onClick={onRetry} className="mt-4 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-bold text-white hover:bg-slate-700">Tentar novamente</button>
    </div>
  )
}
