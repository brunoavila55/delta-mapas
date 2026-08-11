import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { QueryErrorState } from '../components/ListControls'
import { Card, EmptyState, LoadingState, PageHeader, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import { formatDate } from '../lib/format'
import type { CreditAccount, GeneratedMap, MapJob, Paginated, Property } from '../lib/types'

export function DashboardPage() {
  const { session } = useAuth()
  const account = useQuery({ queryKey: ['account'], queryFn: () => api.get<CreditAccount>('/billing/account/') })
  const properties = useQuery({ queryKey: ['properties'], queryFn: () => api.get<Paginated<Property>>('/properties/') })
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => api.get<Paginated<MapJob>>('/map-jobs/') })
  const maps = useQuery({ queryKey: ['maps'], queryFn: () => api.get<Paginated<GeneratedMap>>('/maps/') })

  const stats = [
    { label: 'Créditos disponíveis', value: account.data?.available_balance ?? '—', tone: 'text-emerald-700' },
    { label: 'Propriedades', value: properties.data?.count ?? '—', tone: 'text-slate-950' },
    { label: 'Processamentos', value: jobs.data?.count ?? '—', tone: 'text-slate-950' },
    { label: 'Mapas concluídos', value: maps.data?.count ?? '—', tone: 'text-slate-950' },
  ]
  const dashboardError = account.error ?? properties.error ?? jobs.error ?? maps.error

  if (dashboardError) {
    return (
      <div>
        <PageHeader eyebrow={session?.tenant.name ?? 'Delta Mapas'} title={`Olá, ${session?.user.first_name || session?.user.username}`} />
        <Card><QueryErrorState error={dashboardError} onRetry={() => { void account.refetch(); void properties.refetch(); void jobs.refetch(); void maps.refetch() }} /></Card>
      </div>
    )
  }

  return (
    <div>
      <PageHeader eyebrow={session?.tenant.name ?? 'Delta Mapas'} title={`Olá, ${session?.user.first_name || session?.user.username}`} action={<Link to="/jobs/new" className="rounded-xl bg-emerald-700 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-800">Gerar novo mapa</Link>} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.label} className="p-5">
            <p className="text-xs font-bold uppercase tracking-wider text-slate-500">{stat.label}</p>
            <p className={`mt-3 text-4xl font-bold ${stat.tone}`}>{stat.value}</p>
          </Card>
        ))}
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
        <Card>
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div><h2 className="font-bold text-slate-900">Processamentos recentes</h2><p className="text-xs text-slate-500">Acompanhe o pipeline Sentinel-2</p></div>
            <Link to="/jobs" className="text-sm font-bold text-emerald-700">Ver todos</Link>
          </div>
          {jobs.isLoading ? <LoadingState /> : !jobs.data?.results.length ? <EmptyState title="Nenhum processamento" description="Gere seu primeiro mapa NDVI a partir de uma propriedade." /> : (
            <div className="divide-y divide-slate-100">
              {jobs.data.results.slice(0, 5).map((job) => (
                <div key={job.id} className="flex items-center gap-4 px-5 py-4">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-50 font-black text-emerald-700">N</span>
                  <div className="min-w-0 flex-1"><p className="truncate text-sm font-bold">{job.property_name || 'Área avulsa'}</p><p className="mt-1 truncate text-xs text-slate-500">{job.current_step}</p></div>
                  <StatusBadge status={job.status} />
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="overflow-hidden">
          <div className="bg-emerald-950 p-5 text-white"><p className="text-xs font-bold uppercase tracking-wider text-emerald-300">Último produto</p><h2 className="mt-2 text-xl font-bold">Mapa NDVI</h2></div>
          {maps.isLoading ? <LoadingState /> : maps.data?.results[0] ? (
            <div className="p-5">
              <p className="font-bold">{maps.data.results[0].property_name || 'Área avulsa'}</p>
              <p className="mt-1 text-sm text-slate-500">Cena de {formatDate(maps.data.results[0].scene_date)}</p>
              <Link to="/maps" className="mt-5 inline-flex text-sm font-bold text-emerald-700">Abrir histórico →</Link>
            </div>
          ) : <EmptyState title="Sem mapas" description="Produtos concluídos aparecerão aqui." />}
        </Card>
      </div>
    </div>
  )
}
