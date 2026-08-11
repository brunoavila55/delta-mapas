import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Pagination, QueryErrorState, SearchInput } from '../components/ListControls'
import { PropertyMap, type PropertyMapMode } from '../components/PropertyMap'
import { useToast } from '../components/ToastProvider'
import { Button, Card, EmptyState, LoadingState, PageHeader } from '../components/ui'
import { api } from '../lib/api'
import { errorText, formatArea } from '../lib/format'
import { geometryPolygons, removeHole, removePolygon } from '../lib/geometry'
import { apiPath, LIST_PAGE_SIZE, pageFrom } from '../lib/query'
import type { Geometry, Paginated, Property } from '../lib/types'
import { useDebouncedValue } from '../hooks/useDebouncedValue'

type PropertyFormMode = 'create' | 'edit'
type GeometryInputMode = 'map' | 'geojson'

function isDrawingGeometry(mode: PropertyMapMode) {
  return mode === 'draw-polygon' || mode === 'draw-hole'
}

type PropertyPayload = {
  name: string
  city: string
  state: string
  country: string
  description: string
  geometry: Geometry
}

function parseGeometry(value: string): Geometry {
  const parsed = JSON.parse(value) as Geometry
  if (!['Polygon', 'MultiPolygon'].includes(parsed.type) || !Array.isArray(parsed.coordinates)) {
    throw new Error('GeoJSON deve ser Polygon ou MultiPolygon.')
  }
  return parsed
}

export function PropertiesPage() {
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const [urlParams, setUrlParams] = useSearchParams()
  const page = pageFrom(urlParams.get('page'))
  const search = urlParams.get('search') ?? ''
  const ordering = urlParams.get('ordering') ?? 'name'
  const [searchInput, setSearchInput] = useState(search)
  const debouncedSearch = useDebouncedValue(searchInput)
  const query = useQuery({
    queryKey: ['properties', page, search, ordering],
    queryFn: () => api.get<Paginated<Property>>(apiPath('/properties/', { page, page_size: LIST_PAGE_SIZE, search, ordering })),
    placeholderData: (previous) => previous,
  })
  const [selectedId, setSelectedId] = useState<string>()
  const [formMode, setFormMode] = useState<PropertyFormMode | null>(null)
  const [geometryInputMode, setGeometryInputMode] = useState<GeometryInputMode>('map')
  const [mapMode, setMapMode] = useState<PropertyMapMode>('browse')
  const [formError, setFormError] = useState('')
  const [name, setName] = useState('')
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [draftGeometry, setDraftGeometry] = useState<Geometry | null>(null)
  const [geometryText, setGeometryText] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [importName, setImportName] = useState('')
  const [importCity, setImportCity] = useState('')
  const [importState, setImportState] = useState('')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importError, setImportError] = useState('')
  const properties = useMemo(() => query.data?.results ?? [], [query.data?.results])
  const selected = useMemo(() => properties.find((property) => property.id === selectedId), [properties, selectedId])

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
    setSelectedId(undefined)
    setUrlParams(next)
  }

  function setGeometry(geometry: Geometry | null) {
    setDraftGeometry(geometry)
    setGeometryText(geometry ? JSON.stringify(geometry, null, 2) : '')
  }

  function closePropertyForm() {
    setFormMode(null)
    setFormError('')
    setMapMode('browse')
    setDraftGeometry(null)
    setGeometryText('')
  }

  function startCreate() {
    setShowImport(false)
    setFormMode('create')
    setGeometryInputMode('map')
    setName('')
    setCity('')
    setState('')
    setFormError('')
    setSelectedId(undefined)
    setGeometry(null)
    setMapMode('draw-polygon')
  }

  function startEdit() {
    if (!selected) return
    setShowImport(false)
    setFormMode('edit')
    setGeometryInputMode('map')
    setName(selected.name)
    setCity(selected.city)
    setState(selected.state)
    setFormError('')
    setGeometry(selected.geometry)
    setMapMode('edit')
  }

  const saveProperty = useMutation({
    mutationFn: ({ mode, id, payload }: { mode: PropertyFormMode; id?: string; payload: PropertyPayload }) =>
      mode === 'edit' && id ? api.patch<Property>(`/properties/${id}/`, payload) : api.post<Property>('/properties/', payload),
    onSuccess(property) {
      setSelectedId(property.id)
      closePropertyForm()
      void queryClient.invalidateQueries({ queryKey: ['properties'] })
      notify({ title: formMode === 'edit' ? 'Propriedade atualizada' : 'Propriedade cadastrada', message: property.name, kind: 'success' })
    },
  })

  const importProperty = useMutation({
    mutationFn: (data: FormData) => api.postForm<Property>('/properties/import/', data),
    onSuccess(property) {
      setSelectedId(property.id)
      setShowImport(false)
      setImportName('')
      setImportCity('')
      setImportState('')
      setImportFile(null)
      void queryClient.invalidateQueries({ queryKey: ['properties'] })
      notify({ title: 'Shapefile importado', message: property.name, kind: 'success' })
    },
  })

  const deleteProperty = useMutation({
    mutationFn: ({ id }: { id: string; name: string }) => api.delete(`/properties/${id}/`),
    onSuccess() {
      setSelectedId(undefined)
      closePropertyForm()
      void queryClient.invalidateQueries({ queryKey: ['properties'] })
      notify({ title: 'Propriedade excluída', kind: 'success' })
    },
  })

  async function submitProperty(event: FormEvent) {
    event.preventDefault()
    if (!formMode) return
    setFormError('')
    try {
      const geometry = geometryInputMode === 'geojson' ? parseGeometry(geometryText) : draftGeometry
      if (geometryInputMode === 'map' && isDrawingGeometry(mapMode)) {
        throw new Error('Conclua ou descarte o anel que está sendo desenhado.')
      }
      if (!geometry) throw new Error('Desenhe uma área com pelo menos três pontos.')
      await saveProperty.mutateAsync({
        mode: formMode,
        id: selected?.id,
        payload: { name, city, state, geometry, country: 'BR', description: selected?.description ?? '' },
      })
    } catch (requestError) {
      setFormError(errorText(requestError))
    }
  }

  async function submitImport(event: FormEvent) {
    event.preventDefault()
    setImportError('')
    if (!importFile) {
      setImportError('Selecione um arquivo ZIP com o shapefile.')
      return
    }
    const data = new FormData()
    data.append('file', importFile)
    data.append('name', importName)
    data.append('city', importCity)
    data.append('state', importState)
    data.append('country', 'BR')
    data.append('description', '')
    try {
      await importProperty.mutateAsync(data)
    } catch (requestError) {
      setImportError(errorText(requestError))
    }
  }

  function updateGeometryText(event: ChangeEvent<HTMLTextAreaElement>) {
    const value = event.target.value
    setGeometryText(value)
    try {
      setDraftGeometry(parseGeometry(value))
    } catch {
      setDraftGeometry(null)
    }
  }

  function deletePolygon(polygonIndex: number) {
    if (!draftGeometry) return
    const next = removePolygon(draftGeometry, polygonIndex)
    setGeometry(next)
    setMapMode(next ? 'browse' : 'draw-polygon')
  }

  function deleteHole(polygonIndex: number, ringIndex: number) {
    if (!draftGeometry) return
    setGeometry(removeHole(draftGeometry, polygonIndex, ringIndex))
    setMapMode('browse')
  }

  return (
    <div>
      <PageHeader
        eyebrow="Território"
        title="Propriedades"
        action={(
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => { closePropertyForm(); setShowImport((value) => !value); setImportError('') }} className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              {showImport ? 'Fechar importação' : 'Importar shapefile'}
            </button>
            <Button onClick={formMode ? closePropertyForm : startCreate}>{formMode ? 'Fechar cadastro' : 'Nova propriedade'}</Button>
          </div>
        )}
      />

      <Card className="mb-6 flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <SearchInput value={searchInput} onChange={setSearchInput} placeholder="Buscar por nome, município ou estado" />
        <label className="flex items-center gap-2 text-xs font-bold text-slate-500">Ordenar
          <select value={ordering} onChange={(event) => setListParam('ordering', event.target.value)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 outline-none focus:border-emerald-600">
            <option value="name">Nome A–Z</option>
            <option value="-name">Nome Z–A</option>
            <option value="-created_at">Mais recentes</option>
            <option value="-area_hectares">Maior área</option>
          </select>
        </label>
      </Card>

      {showImport && (
        <Card className="mb-6 p-5">
          <div className="mb-4"><h2 className="font-bold text-slate-950">Importar shapefile</h2><p className="mt-1 text-sm text-slate-500">Envie um ZIP contendo um único conjunto .shp, .shx, .dbf e .prj.</p></div>
          <form onSubmit={submitImport} className="grid gap-4 lg:grid-cols-[1fr_1fr_auto] lg:items-end">
            <label className="block text-sm font-semibold">Nome<input value={importName} onChange={(event) => setImportName(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 px-3.5 py-2.5 outline-none focus:border-emerald-600" required /></label>
            <label className="block text-sm font-semibold">Arquivo ZIP<input type="file" accept=".zip,application/zip" onChange={(event) => setImportFile(event.target.files?.[0] ?? null)} className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-emerald-50 file:px-3 file:py-1.5 file:font-semibold file:text-emerald-800" required /></label>
            <Button disabled={importProperty.isPending}>{importProperty.isPending ? 'Importando…' : 'Importar área'}</Button>
            <label className="block text-sm font-semibold">Município<input value={importCity} onChange={(event) => setImportCity(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 px-3.5 py-2.5 outline-none focus:border-emerald-600" /></label>
            <label className="block text-sm font-semibold">Estado<input value={importState} onChange={(event) => setImportState(event.target.value)} maxLength={120} className="mt-1.5 w-full rounded-xl border border-slate-300 px-3.5 py-2.5 outline-none focus:border-emerald-600" /></label>
            {importFile && <p className="text-xs text-slate-500">{importFile.name} · {(importFile.size / 1024).toFixed(1)} kB</p>}
          </form>
          {importError && <p className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{importError}</p>}
        </Card>
      )}

      {formMode && (
        <Card className="mb-6 p-5">
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
            <div><h2 className="font-bold text-slate-950">{formMode === 'create' ? 'Cadastrar propriedade' : `Editar ${selected?.name ?? 'propriedade'}`}</h2><p className="mt-1 text-sm text-slate-500">Desenhe no mapa ou cole uma geometria GeoJSON.</p></div>
            <div className="flex rounded-xl bg-slate-100 p-1 text-xs font-bold">
              <button type="button" onClick={() => { setGeometryInputMode('map'); setMapMode(draftGeometry ? 'edit' : 'draw-polygon') }} className={`rounded-lg px-3 py-2 ${geometryInputMode === 'map' ? 'bg-white text-emerald-800 shadow-sm' : 'text-slate-500'}`}>Desenhar no mapa</button>
              <button type="button" onClick={() => { setGeometryInputMode('geojson'); setMapMode('browse') }} className={`rounded-lg px-3 py-2 ${geometryInputMode === 'geojson' ? 'bg-white text-emerald-800 shadow-sm' : 'text-slate-500'}`}>Colar GeoJSON</button>
            </div>
          </div>
          <form onSubmit={submitProperty} className="grid gap-4 lg:grid-cols-[1fr_1fr_auto] lg:items-end">
            <label className="block text-sm font-semibold">Nome<input value={name} onChange={(event) => setName(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 px-3.5 py-2.5 outline-none focus:border-emerald-600" required /></label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-sm font-semibold">Município<input value={city} onChange={(event) => setCity(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 px-3.5 py-2.5 outline-none focus:border-emerald-600" /></label>
              <label className="block text-sm font-semibold">Estado<input value={state} onChange={(event) => setState(event.target.value)} maxLength={120} className="mt-1.5 w-full rounded-xl border border-slate-300 px-3.5 py-2.5 outline-none focus:border-emerald-600" /></label>
            </div>
            <Button disabled={saveProperty.isPending || (geometryInputMode === 'map' && isDrawingGeometry(mapMode))}>{saveProperty.isPending ? 'Salvando…' : formMode === 'edit' ? 'Salvar alterações' : 'Salvar propriedade'}</Button>
            {geometryInputMode === 'geojson' && (
              <label className="block text-sm font-semibold lg:col-span-3">Geometria GeoJSON<textarea value={geometryText} onChange={updateGeometryText} className="mt-1.5 h-48 w-full rounded-xl border border-slate-300 bg-slate-950 p-4 font-mono text-xs leading-5 text-emerald-200 outline-none focus:border-emerald-500" spellCheck={false} required /></label>
            )}
            {geometryInputMode === 'map' && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600 lg:col-span-3">
                <span className={`rounded-full px-2.5 py-1 font-bold ${draftGeometry ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>{draftGeometry ? 'Geometria pronta' : 'Aguardando desenho'}</span>
                {draftGeometry && !isDrawingGeometry(mapMode) && <button type="button" onClick={() => setMapMode('edit')} className="font-bold text-emerald-700 hover:text-emerald-900">Editar vértices</button>}
                {draftGeometry && !isDrawingGeometry(mapMode) && <button type="button" onClick={() => setMapMode('draw-polygon')} className="font-bold text-amber-700 hover:text-amber-900">Adicionar componente</button>}
                {draftGeometry && !isDrawingGeometry(mapMode) && <button type="button" onClick={() => setMapMode('draw-hole')} className="font-bold text-sky-700 hover:text-sky-900">Adicionar furo</button>}
                {!isDrawingGeometry(mapMode) && <button type="button" onClick={() => { setGeometry(null); setMapMode('draw-polygon') }} className="font-bold text-slate-600 hover:text-slate-900">Redesenhar tudo</button>}
              </div>
            )}
            {geometryInputMode === 'map' && draftGeometry && !isDrawingGeometry(mapMode) && (
              <div className="grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs lg:col-span-3">
                <p className="font-bold text-slate-700">
                  {geometryPolygons(draftGeometry).length} componente(s) · {geometryPolygons(draftGeometry).reduce((total, polygon) => total + polygon.length - 1, 0)} furo(s)
                </p>
                {geometryPolygons(draftGeometry).map((polygon, polygonIndex) => (
                  <div key={polygonIndex} className="flex flex-wrap items-center gap-2 rounded-lg bg-white px-3 py-2">
                    <span className="mr-auto font-semibold text-slate-600">Componente {polygonIndex + 1} · {polygon.length - 1} furo(s)</span>
                    {polygon.slice(1).map((_, holeIndex) => (
                      <button key={holeIndex} type="button" onClick={() => deleteHole(polygonIndex, holeIndex + 1)} className="font-bold text-sky-700 hover:text-sky-900">Remover furo {holeIndex + 1}</button>
                    ))}
                    <button type="button" onClick={() => deletePolygon(polygonIndex)} className="font-bold text-rose-700 hover:text-rose-900">Remover componente</button>
                  </div>
                ))}
              </div>
            )}
          </form>
          {formError && <p className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{formError}</p>}
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
        <Card className="overflow-hidden">
          <div className="border-b border-slate-100 px-5 py-4"><h2 className="font-bold">Áreas cadastradas</h2><p className="text-xs text-slate-500">{query.data?.count ?? 0} propriedades</p></div>
          {query.isLoading ? <LoadingState /> : query.isError ? <QueryErrorState error={query.error} onRetry={() => void query.refetch()} /> : !properties.length ? <EmptyState title={search ? 'Nenhuma propriedade encontrada' : 'Nenhuma propriedade'} description={search ? 'Revise o termo da busca ou limpe o filtro.' : 'Cadastre uma geometria para começar.'} /> : (
            <div className="max-h-[520px] divide-y divide-slate-100 overflow-y-auto">
              {properties.map((property) => (
                <button key={property.id} disabled={Boolean(formMode)} onClick={() => { setSelectedId(property.id); setMapMode('browse') }} className={`w-full px-5 py-4 text-left transition hover:bg-slate-50 disabled:cursor-default disabled:hover:bg-inherit ${selectedId === property.id ? 'bg-emerald-50' : ''}`}>
                  <p className="font-bold text-slate-900">{property.name}</p>
                  <div className="mt-1 flex items-center justify-between gap-3 text-xs text-slate-500"><span>{[property.city, property.state].filter(Boolean).join(' · ') || 'Local não informado'}</span><span>{formatArea(property.area_hectares)}</span></div>
                </button>
              ))}
            </div>
          )}
          {selected && !formMode && (
            <div className="flex items-center justify-between border-t border-slate-100 p-4">
              <button onClick={startEdit} className="text-xs font-bold text-emerald-700 hover:text-emerald-900">Editar propriedade</button>
              <button onClick={() => { if (window.confirm(`Excluir ${selected.name}?`)) deleteProperty.mutate({ id: selected.id, name: selected.name }) }} className="text-xs font-bold text-rose-700 hover:text-rose-800">Excluir</button>
            </div>
          )}
          <Pagination page={page} pageSize={LIST_PAGE_SIZE} count={query.data?.count ?? 0} onPageChange={(value) => setListParam('page', value)} />
        </Card>
        <Card className="p-2">
          <PropertyMap
            properties={properties}
            selectedId={selectedId}
            onSelect={(property) => setSelectedId(property.id)}
            mode={geometryInputMode === 'map' ? mapMode : 'browse'}
            draftGeometry={formMode ? draftGeometry : null}
            onDraftChange={setGeometry}
            onFinishEditing={() => setMapMode('browse')}
            onCancelDrawing={() => setMapMode('browse')}
          />
        </Card>
      </div>
    </div>
  )
}
