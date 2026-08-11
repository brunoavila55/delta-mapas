import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Pagination, QueryErrorState } from '../components/ListControls'
import { Card, EmptyState, LoadingState, PageHeader } from '../components/ui'
import { api } from '../lib/api'
import { formatDate } from '../lib/format'
import { apiPath, LIST_PAGE_SIZE, pageFrom } from '../lib/query'
import type { CreditAccount, CreditTransaction, Paginated, ProcessingPrice } from '../lib/types'

const transactionLabels: Record<string, string> = {
  PURCHASE: 'Compra', RESERVE: 'Reserva', CAPTURE: 'Consumo', RELEASE: 'Liberação', REFUND: 'Estorno', BONUS: 'Bônus', ADMIN_ADJUSTMENT: 'Ajuste administrativo',
}

export function BillingPage() {
  const [urlParams, setUrlParams] = useSearchParams()
  const page = pageFrom(urlParams.get('page'))
  const type = urlParams.get('type') ?? ''
  const ordering = urlParams.get('ordering') ?? '-created_at'
  const account = useQuery({ queryKey: ['account'], queryFn: () => api.get<CreditAccount>('/billing/account/') })
  const transactions = useQuery({
    queryKey: ['transactions', page, type, ordering],
    queryFn: () => api.get<Paginated<CreditTransaction>>(apiPath('/billing/transactions/', { page, page_size: LIST_PAGE_SIZE, type, ordering })),
    placeholderData: (previous) => previous,
  })
  const prices = useQuery({ queryKey: ['prices'], queryFn: () => api.get<ProcessingPrice[]>('/billing/prices/') })

  function setListParam(key: string, value: string | number) {
    const next = new URLSearchParams(urlParams)
    if (value) next.set(key, String(value))
    else next.delete(key)
    if (key !== 'page') next.set('page', '1')
    setUrlParams(next)
  }

  const summaryError = account.error ?? prices.error

  return (
    <div>
      <PageHeader eyebrow="Conta de processamento" title="Créditos" />
      {summaryError ? <Card className="mb-5"><QueryErrorState error={summaryError} onRetry={() => { void account.refetch(); void prices.refetch() }} /></Card> : (
        <div className="grid gap-4 md:grid-cols-3">
          <Card className="p-5"><p className="text-xs font-bold uppercase tracking-wider text-slate-500">Disponíveis</p><p className="mt-3 text-4xl font-bold text-emerald-700">{account.data?.available_balance ?? '—'}</p></Card>
          <Card className="p-5"><p className="text-xs font-bold uppercase tracking-wider text-slate-500">Reservados</p><p className="mt-3 text-4xl font-bold text-amber-600">{account.data?.reserved_balance ?? '—'}</p></Card>
          <Card className="p-5"><p className="text-xs font-bold uppercase tracking-wider text-slate-500">Preço NDVI</p><p className="mt-3 text-4xl font-bold text-slate-950">{prices.data?.find((price) => price.index_type === 'NDVI')?.credit_cost ?? '—'}</p><p className="mt-1 text-xs text-slate-500">crédito por mapa concluído</p></Card>
        </div>
      )}
      <Card className="mt-6 overflow-hidden">
        <div className="flex flex-col justify-between gap-3 border-b border-slate-100 px-5 py-4 lg:flex-row lg:items-center">
          <div><h2 className="font-bold">Histórico do ledger</h2><p className="text-xs text-slate-500">Movimentações auditáveis da organização</p></div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor="transaction-type">Tipo de evento</label>
            <select id="transaction-type" value={type} onChange={(event) => setListParam('type', event.target.value)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 outline-none focus:border-emerald-600">
              <option value="">Todos os eventos</option>
              {Object.entries(transactionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <label className="sr-only" htmlFor="transaction-ordering">Ordenação</label>
            <select id="transaction-ordering" value={ordering} onChange={(event) => setListParam('ordering', event.target.value)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 outline-none focus:border-emerald-600">
              <option value="-created_at">Mais recentes</option>
              <option value="created_at">Mais antigos</option>
              <option value="-amount">Maior valor</option>
            </select>
          </div>
        </div>
        {transactions.isLoading ? <LoadingState /> : transactions.isError ? <QueryErrorState error={transactions.error} onRetry={() => void transactions.refetch()} /> : !transactions.data?.results.length ? <EmptyState title="Sem movimentações" description={type ? 'Nenhum evento corresponde ao filtro selecionado.' : 'Reservas, capturas e liberações aparecerão aqui.'} /> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[650px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500"><tr><th className="px-5 py-3">Evento</th><th className="px-5 py-3">Data</th><th className="px-5 py-3">Valor</th><th className="px-5 py-3">Disponível após</th><th className="px-5 py-3">Reservado após</th></tr></thead><tbody className="divide-y divide-slate-100">{transactions.data.results.map((transaction) => <tr key={transaction.id}><td className="px-5 py-3 font-semibold">{transactionLabels[transaction.transaction_type] ?? transaction.transaction_type}</td><td className="px-5 py-3 text-slate-500">{formatDate(transaction.created_at, true)}</td><td className="px-5 py-3 font-mono">{transaction.amount}</td><td className="px-5 py-3">{transaction.available_balance_after}</td><td className="px-5 py-3">{transaction.reserved_balance_after}</td></tr>)}</tbody></table></div>
        )}
        <Pagination page={page} pageSize={LIST_PAGE_SIZE} count={transactions.data?.count ?? 0} onPageChange={(value) => setListParam('page', value)} />
      </Card>
    </div>
  )
}
