import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { Pagination, QueryErrorState, SearchInput } from '../components/ListControls'
import { useToast } from '../components/ToastProvider'
import { Card, EmptyState, LoadingState, PageHeader, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import { errorText, formatDate } from '../lib/format'
import { apiPath, LIST_PAGE_SIZE, pageFrom } from '../lib/query'
import type { MapJob, MapJobStatus, Paginated } from '../lib/types'

const statusOptions: Array<{ value: '' | MapJobStatus; label: string }> = [
  { value: '', label: 'Todos os status' },
  { value: 'PENDING', label: 'Pendente' },
  { value: 'SEARCHING_SCENE', label: 'Buscando cena' },
  { value: 'DOWNLOADING', label: 'Baixando' },
  { value: 'PREPROCESSING', label: 'Preparando' },
  { value: 'PROCESSING', label: 'Processando' },
  { value: 'RENDERING', label: 'Renderizando' },
  { value: 'UPLOADING', label: 'Enviando' },
  { value: 'COMPLETED', label: 'Concluído' },
  { value: 'FAILED', label: 'Falhou' },
  { value: 'CANCELLED', label: 'Cancelado' },
]

export function JobsPage() {
  const { session } = useAuth()
  const canManageJobs = session?.tenant.role !== 'VIEWER'
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const reprocessKeys = useRef(new Map<string, string>())
  const [urlParams, setUrlParams] = useSearchParams()
  const page = pageFrom(urlParams.get('page'))
  const search = urlParams.get('search') ?? ''
  const status = urlParams.get('status') ?? ''
  const ordering = urlParams.get('ordering') ?? '-created_at'
  const [searchInput, setSearchInput] = useState(search)
  const debouncedSearch = useDebouncedValue(searchInput)
  const jobs = useQuery({
    queryKey: ['jobs', page, search, status, ordering],
    queryFn: () => api.get<Paginated<MapJob>>(apiPath('/map-jobs/', { page, page_size: LIST_PAGE_SIZE, search, status, ordering })),
    placeholderData: (previous) => previous,
    refetchInterval: (query) => {
      const data = query.state.data as Paginated<MapJob> | undefined
      return data?.results.some((job) => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status)) ? 5_000 : false
    },
  })

  const cancelJob = useMutation({
    mutationFn: (id: string) => api.post<MapJob>(`/map-jobs/${id}/cancel/`),
    onSuccess(job) {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      void queryClient.invalidateQueries({ queryKey: ['account'] })
      void queryClient.invalidateQueries({ queryKey: ['transactions'] })
      notify({ title: 'Processamento cancelado', message: `${job.credit_cost} crédito devolvido ao saldo.`, kind: 'success' })
    },
    onError(error) {
      notify({ title: 'Não foi possível cancelar', message: errorText(error), kind: 'error' })
    },
  })

  const reprocessJob = useMutation({
    mutationFn: ({ id, idempotencyKey }: { id: string; idempotencyKey: string }) => api.post<MapJob>(`/map-jobs/${id}/reprocess/`, undefined, { 'Idempotency-Key': idempotencyKey }),
    onSuccess(job, variables) {
      reprocessKeys.current.delete(variables.id)
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      void queryClient.invalidateQueries({ queryKey: ['account'] })
      void queryClient.invalidateQueries({ queryKey: ['transactions'] })
      notify({ title: 'Reprocessamento enfileirado', message: `${job.credit_cost} crédito reservado.`, kind: 'success' })
    },
    onError(error) {
      notify({ title: 'Não foi possível reprocessar', message: errorText(error), kind: 'error' })
    },
  })

  function requestReprocess(job: MapJob) {
    if (!window.confirm(`Reprocessar este job por ${job.credit_cost} crédito?`)) return
    const idempotencyKey = reprocessKeys.current.get(job.id) ?? crypto.randomUUID()
    reprocessKeys.current.set(job.id, idempotencyKey)
    reprocessJob.mutate({ id: job.id, idempotencyKey })
  }

  useEffect(() => setSearchInput(search), [search])
  useEffect(() => {
    if (debouncedSearch === search) return
    const next = new URLSearchParams(urlParams)
    if (debouncedSearch) next.set('search', debouncedSearch)
    else next.delete('search')
    next.set('page', '1')
    setUrlParams(next, { replace: true })
  }, [debouncedSearch, search, setUrlParams, urlParams])

  function setListParam(key: string, value: string | number) {
    const next = new URLSearchParams(urlParams)
    if (value) next.set(key, String(value))
    else next.delete(key)
    if (key !== 'page') next.set('page', '1')
    setUrlParams(next)
  }

  const hasFilters = Boolean(search || status)

  return (
    <div>
      <PageHeader eyebrow="Pipeline Sentinel-2" title="Processamentos" action={canManageJobs ? <Link to="/jobs/new" className="rounded-xl bg-emerald-700 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-800">Novo mapa NDVI</Link> : undefined} />
      <Card className="mb-5 flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
        <SearchInput value={searchInput} onChange={setSearchInput} placeholder="Buscar propriedade, cena ou etapa" />
        <div className="flex flex-col gap-3 sm:flex-row">
          <label className="sr-only" htmlFor="job-status">Status</label>
          <select id="job-status" value={status} onChange={(event) => setListParam('status', event.target.value)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 outline-none focus:border-emerald-600">
            {statusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <label className="sr-only" htmlFor="job-ordering">Ordenação</label>
          <select id="job-ordering" value={ordering} onChange={(event) => setListParam('ordering', event.target.value)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 outline-none focus:border-emerald-600">
            <option value="-created_at">Mais recentes</option>
            <option value="created_at">Mais antigos</option>
            <option value="-progress">Maior progresso</option>
          </select>
        </div>
      </Card>
      <Card className="overflow-hidden">
        {jobs.isLoading ? <LoadingState /> : jobs.isError ? <QueryErrorState error={jobs.error} onRetry={() => void jobs.refetch()} /> : !jobs.data?.results.length ? <EmptyState title={hasFilters ? 'Nenhum processamento encontrado' : 'Nenhum processamento'} description={hasFilters ? 'Revise a busca ou os filtros selecionados.' : 'Solicite um mapa NDVI para acompanhar cada etapa aqui.'} /> : (
          <div className="divide-y divide-slate-100">
            {jobs.data.results.map((job) => (
              <article key={job.id} className="p-5">
                <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-3"><h2 className="font-bold text-slate-950">{job.property_name || 'Área avulsa'}</h2><StatusBadge status={job.status} /></div>
                    <p className="mt-2 text-sm text-slate-600">{job.current_step}</p>
                    <p className="mt-1 text-xs text-slate-400">Criado em {formatDate(job.created_at, true)} · {job.credit_cost} crédito</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {job.generated_map_id && <Link to="/maps" className="text-sm font-bold text-emerald-700">Ver mapa</Link>}
                    {canManageJobs && (!['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status) ? (
                      <button type="button" disabled={cancelJob.isPending} onClick={() => { if (window.confirm('Cancelar este processamento e devolver o crédito reservado?')) cancelJob.mutate(job.id) }} className="text-sm font-bold text-rose-700 disabled:opacity-50">{cancelJob.isPending && cancelJob.variables === job.id ? 'Cancelando…' : 'Cancelar'}</button>
                    ) : (
                      <button type="button" disabled={reprocessJob.isPending} onClick={() => requestReprocess(job)} className="text-sm font-bold text-amber-700 disabled:opacity-50">{reprocessJob.isPending && reprocessJob.variables?.id === job.id ? 'Enfileirando…' : 'Reprocessar'}</button>
                    ))}
                    <span className="font-mono text-xs text-slate-400">{job.id.slice(0, 8)}</span>
                  </div>
                </div>
                {job.reprocessed_from_id && <p className="mt-3 text-xs font-semibold text-amber-700">Reprocessamento de {job.reprocessed_from_id.slice(0, 8)}</p>}
                <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full transition-all ${job.status === 'FAILED' ? 'bg-rose-500' : job.status === 'CANCELLED' ? 'bg-slate-400' : 'bg-emerald-600'}`} style={{ width: `${job.progress}%` }} /></div>
                <div className="mt-2 flex justify-between text-xs"><span className="font-semibold text-slate-500">{job.progress}%</span><span className="text-slate-400">{job.date_from && job.date_to ? `${job.date_from} → ${job.date_to}` : job.requested_scene_date}</span></div>
                {job.error_message && <p className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700"><strong>{job.error_code}:</strong> {job.error_message}</p>}
              </article>
            ))}
          </div>
        )}
        <Pagination page={page} pageSize={LIST_PAGE_SIZE} count={jobs.data?.count ?? 0} onPageChange={(value) => setListParam('page', value)} />
      </Card>
    </div>
  )
}
