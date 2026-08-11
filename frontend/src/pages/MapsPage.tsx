import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { Pagination, QueryErrorState, SearchInput } from '../components/ListControls'
import { SecureImage } from '../components/SecureImage'
import { useToast } from '../components/ToastProvider'
import { Card, EmptyState, LoadingState, PageHeader } from '../components/ui'
import { api } from '../lib/api'
import { errorText, formatDate } from '../lib/format'
import { apiPath, LIST_PAGE_SIZE, pageFrom } from '../lib/query'
import type { GeneratedMap, Paginated } from '../lib/types'

async function download(url: string, filename: string) {
  const blob = await api.download(url)
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(objectUrl)
}

export function MapsPage() {
  const { notify } = useToast()
  const [urlParams, setUrlParams] = useSearchParams()
  const page = pageFrom(urlParams.get('page'))
  const search = urlParams.get('search') ?? ''
  const ordering = urlParams.get('ordering') ?? '-created_at'
  const [searchInput, setSearchInput] = useState(search)
  const [downloading, setDownloading] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput)
  const maps = useQuery({
    queryKey: ['maps', page, search, ordering],
    queryFn: () => api.get<Paginated<GeneratedMap>>(apiPath('/maps/', { page, page_size: LIST_PAGE_SIZE, search, ordering })),
    placeholderData: (previous) => previous,
  })

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

  async function startDownload(map: GeneratedMap, format: 'png' | 'pdf') {
    const key = `${map.id}-${format}`
    setDownloading(key)
    try {
      await download(format === 'png' ? map.png_download_url : map.pdf_download_url, `delta-mapas-${map.id}.${format}`)
      notify({ title: `Download ${format.toUpperCase()} iniciado`, message: map.property_name || 'Área avulsa', kind: 'success' })
    } catch (requestError) {
      notify({ title: 'Falha no download', message: errorText(requestError), kind: 'error' })
    } finally {
      setDownloading('')
    }
  }

  return (
    <div>
      <PageHeader eyebrow="Produtos finais" title="Mapas gerados" />
      <Card className="mb-5 flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <SearchInput value={searchInput} onChange={setSearchInput} placeholder="Buscar propriedade ou cena Sentinel" />
        <label className="flex items-center gap-2 text-xs font-bold text-slate-500">Ordenar
          <select value={ordering} onChange={(event) => setListParam('ordering', event.target.value)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 outline-none focus:border-emerald-600">
            <option value="-created_at">Mais recentes</option>
            <option value="created_at">Mais antigos</option>
            <option value="-scene_date">Cena mais recente</option>
            <option value="cloud_cover">Menor nebulosidade</option>
          </select>
        </label>
      </Card>
      {maps.isLoading ? <LoadingState /> : maps.isError ? <Card><QueryErrorState error={maps.error} onRetry={() => void maps.refetch()} /></Card> : !maps.data?.results.length ? <Card><EmptyState title={search ? 'Nenhum mapa encontrado' : 'Nenhum mapa concluído'} description={search ? 'Revise o termo da busca ou limpe o filtro.' : 'Quando um processamento terminar, os produtos PNG e PDF aparecerão aqui.'} /></Card> : (
        <div className="grid gap-6 md:grid-cols-2 2xl:grid-cols-3">
          {maps.data.results.map((map) => {
            const statistics = (map.metadata.statistics ?? {}) as Record<string, number>
            return (
              <Card key={map.id} className="overflow-hidden">
                <SecureImage src={map.png_download_url} alt={`Mapa NDVI de ${map.property_name || 'área avulsa'}`} />
                <div className="p-5">
                  <div className="flex items-start justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-wider text-emerald-700">{map.index_type}</p><h2 className="mt-1 text-lg font-bold">{map.property_name || 'Área avulsa'}</h2></div><span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-bold text-emerald-800">Concluído</span></div>
                  <p className="mt-2 text-sm text-slate-500">Cena de {formatDate(map.scene_date)} · {map.cloud_cover ?? '—'}% nuvens</p>
                  <div className="mt-4 grid grid-cols-3 gap-2 rounded-xl bg-slate-50 p-3 text-center"><div><p className="text-[10px] font-bold uppercase text-slate-400">Mín.</p><p className="text-sm font-bold">{statistics.minimum?.toFixed(2) ?? '—'}</p></div><div><p className="text-[10px] font-bold uppercase text-slate-400">Média</p><p className="text-sm font-bold">{statistics.mean?.toFixed(2) ?? '—'}</p></div><div><p className="text-[10px] font-bold uppercase text-slate-400">Máx.</p><p className="text-sm font-bold">{statistics.maximum?.toFixed(2) ?? '—'}</p></div></div>
                  <div className="mt-5 flex gap-3"><button onClick={() => void startDownload(map, 'png')} disabled={Boolean(downloading)} className="flex-1 rounded-xl border border-emerald-700 px-3 py-2 text-sm font-bold text-emerald-700 hover:bg-emerald-50 disabled:opacity-50">{downloading === `${map.id}-png` ? 'Baixando…' : 'Baixar PNG'}</button><button onClick={() => void startDownload(map, 'pdf')} disabled={Boolean(downloading)} className="flex-1 rounded-xl bg-emerald-700 px-3 py-2 text-sm font-bold text-white hover:bg-emerald-800 disabled:opacity-50">{downloading === `${map.id}-pdf` ? 'Baixando…' : 'Baixar PDF'}</button></div>
                </div>
              </Card>
            )
          })}
        </div>
      )}
      {(maps.data?.count ?? 0) > LIST_PAGE_SIZE && <div className="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><Pagination page={page} pageSize={LIST_PAGE_SIZE} count={maps.data?.count ?? 0} onPageChange={(value) => setListParam('page', value)} /></div>}
    </div>
  )
}
