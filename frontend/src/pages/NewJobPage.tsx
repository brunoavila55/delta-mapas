import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button, Card, PageHeader } from '../components/ui'
import { useToast } from '../components/ToastProvider'
import { api } from '../lib/api'
import { errorText } from '../lib/format'
import { apiPath } from '../lib/query'
import type { CreditAccount, MapJob, Paginated, ProcessingPrice, Property } from '../lib/types'

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10)
}

export function NewJobPage() {
  const { notify } = useToast()
  const now = new Date()
  const thirtyDaysAgo = new Date(now)
  thirtyDaysAgo.setDate(now.getDate() - 30)
  const [propertyId, setPropertyId] = useState('')
  const [dateFrom, setDateFrom] = useState(isoDate(thirtyDaysAgo))
  const [dateTo, setDateTo] = useState(isoDate(now))
  const [maxCloudCover, setMaxCloudCover] = useState('30')
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const properties = useQuery({ queryKey: ['properties', 'job-options'], queryFn: () => api.get<Paginated<Property>>(apiPath('/properties/', { page_size: 100, ordering: 'name' })) })
  const account = useQuery({ queryKey: ['account'], queryFn: () => api.get<CreditAccount>('/billing/account/') })
  const prices = useQuery({ queryKey: ['prices'], queryFn: () => api.get<ProcessingPrice[]>('/billing/prices/') })
  const ndviPrice = prices.data?.find((price) => price.index_type === 'NDVI')?.credit_cost ?? 1

  const createJob = useMutation({
    mutationFn: () => api.post<MapJob>('/map-jobs/', { index_type: 'NDVI', property_id: propertyId, date_from: dateFrom, date_to: dateTo, max_cloud_cover: maxCloudCover }, { 'Idempotency-Key': crypto.randomUUID() }),
    onSuccess(job) {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      void queryClient.invalidateQueries({ queryKey: ['account'] })
      notify({ title: 'Processamento enfileirado', message: `${job.property_name || 'Área avulsa'} · ${job.credit_cost} crédito reservado`, kind: 'success' })
      navigate('/jobs')
    },
  })

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      await createJob.mutateAsync()
    } catch (requestError) {
      setError(errorText(requestError))
    }
  }

  return (
    <div>
      <PageHeader eyebrow="Novo processamento" title="Gerar mapa NDVI" action={<Link to="/jobs" className="text-sm font-bold text-slate-600">← Voltar</Link>} />
      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <Card className="p-6">
          <form className="space-y-6" onSubmit={submit}>
            <div><label className="text-sm font-bold text-slate-700">Propriedade</label><select value={propertyId} onChange={(event) => setPropertyId(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3 outline-none focus:border-emerald-600" required><option value="">Selecione uma propriedade</option>{properties.data?.results.map((property) => <option key={property.id} value={property.id}>{property.name} · {Number(property.area_hectares).toFixed(2)} ha</option>)}</select>{!properties.data?.results.length && <p className="mt-2 text-xs text-amber-700">Cadastre uma propriedade antes de gerar o mapa.</p>}</div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="text-sm font-bold text-slate-700">Data inicial<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} max={dateTo} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-emerald-600" required /></label>
              <label className="text-sm font-bold text-slate-700">Data final<input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} min={dateFrom} max={isoDate(now)} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-emerald-600" required /></label>
            </div>
            <label className="block text-sm font-bold text-slate-700">Cobertura máxima de nuvens: {maxCloudCover}%<input type="range" min="0" max="100" step="5" value={maxCloudCover} onChange={(event) => setMaxCloudCover(event.target.value)} className="mt-3 w-full accent-emerald-700" /></label>
            {error && <p className="rounded-xl bg-rose-50 p-4 text-sm text-rose-700">{error}</p>}
            <Button disabled={createJob.isPending || !propertyId || (account.data?.available_balance ?? 0) < ndviPrice}>{createJob.isPending ? 'Enfileirando…' : `Gerar mapa por ${ndviPrice} crédito`}</Button>
          </form>
        </Card>
        <Card className="h-fit overflow-hidden">
          <div className="bg-emerald-950 p-5 text-white"><p className="text-xs font-bold uppercase tracking-wider text-emerald-300">Resumo</p><p className="mt-2 text-3xl font-bold">{account.data?.available_balance ?? '—'}</p><p className="text-sm text-emerald-100/70">créditos disponíveis</p></div>
          <div className="space-y-4 p-5 text-sm"><div className="flex justify-between"><span className="text-slate-500">Produto</span><strong>NDVI Sentinel-2</strong></div><div className="flex justify-between"><span className="text-slate-500">Resolução</span><strong>10 metros</strong></div><div className="flex justify-between"><span className="text-slate-500">Entrega</span><strong>PNG + PDF</strong></div><p className="border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500">O crédito é reservado ao enviar. Ele só é consumido depois que os dois produtos forem armazenados; falhas devolvem a reserva.</p></div>
        </Card>
      </div>
    </div>
  )
}
