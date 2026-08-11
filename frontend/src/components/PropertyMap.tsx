import maplibregl, { type GeoJSONSource, type Map as MapLibreMap } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import {
  appendHole,
  appendPolygon,
  geometryPolygons,
  moveVertex,
  type VertexAddress,
} from '../lib/geometry'
import type { Geometry, Property } from '../lib/types'

export type PropertyMapMode = 'browse' | 'draw-polygon' | 'draw-hole' | 'edit'

function isDrawingMode(mode: PropertyMapMode): mode is 'draw-polygon' | 'draw-hole' {
  return mode === 'draw-polygon' || mode === 'draw-hole'
}

function composeDrawing(
  base: Geometry | null,
  points: number[][],
  drawingMode: 'draw-polygon' | 'draw-hole',
) {
  return drawingMode === 'draw-hole'
    ? appendHole(base, points)
    : appendPolygon(base, points)
}

function extendBounds(bounds: maplibregl.LngLatBounds, coordinates: unknown): void {
  if (!Array.isArray(coordinates)) return
  if (coordinates.length >= 2 && typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number') {
    bounds.extend([coordinates[0], coordinates[1]])
    return
  }
  coordinates.forEach((child) => extendBounds(bounds, child))
}

function geometryVertices(geometry: Geometry | null, mode: PropertyMapMode) {
  if (!geometry || mode !== 'edit') return []
  return geometryPolygons(geometry).flatMap((polygon, polygonIndex) =>
    polygon.flatMap((ring, ringIndex) =>
      ring.slice(0, -1).map((coordinates, vertexIndex) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates },
        properties: { polygon: polygonIndex, ring: ringIndex, vertex: vertexIndex },
      })),
    ),
  )
}

type PropertyMapProps = {
  properties: Property[]
  selectedId?: string
  onSelect: (property: Property) => void
  mode?: PropertyMapMode
  draftGeometry?: Geometry | null
  onDraftChange?: (geometry: Geometry | null) => void
  onFinishEditing?: () => void
  onCancelDrawing?: () => void
}

export function PropertyMap({
  properties,
  selectedId,
  onSelect,
  mode = 'browse',
  draftGeometry = null,
  onDraftChange = () => undefined,
  onFinishEditing = () => undefined,
  onCancelDrawing = () => undefined,
}: PropertyMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const selectRef = useRef(onSelect)
  const propertiesRef = useRef(properties)
  const modeRef = useRef(mode)
  const draftRef = useRef(draftGeometry)
  const draftChangeRef = useRef(onDraftChange)
  const dragRef = useRef<VertexAddress | null>(null)
  const drawPointsRef = useRef<number[][]>([])
  const drawBaseRef = useRef<Geometry | null>(null)
  const previousModeRef = useRef<PropertyMapMode>('browse')
  const [drawPoints, setDrawPoints] = useState<number[][]>([])
  const [drawingError, setDrawingError] = useState('')
  const [loaded, setLoaded] = useState(false)

  selectRef.current = onSelect
  propertiesRef.current = properties
  modeRef.current = mode
  draftRef.current = draftGeometry
  draftChangeRef.current = onDraftChange

  useEffect(() => {
    const previousMode = previousModeRef.current
    if (isDrawingMode(mode) && !isDrawingMode(previousMode)) {
      drawBaseRef.current = draftGeometry
      drawPointsRef.current = []
      setDrawPoints([])
      setDrawingError('')
    } else if (!isDrawingMode(mode)) {
      drawPointsRef.current = []
      setDrawPoints([])
      setDrawingError('')
    }
    previousModeRef.current = mode
  }, [draftGeometry, mode])

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e7eee7' } }] },
      center: [-47.9, -15.8],
      zoom: 8,
      attributionControl: false,
      doubleClickZoom: false,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-right')
    map.on('load', () => {
      map.addSource('properties', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addSource('draft', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addSource('draft-progress', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addSource('draft-vertices', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addLayer({ id: 'properties-fill', type: 'fill', source: 'properties', paint: { 'fill-color': ['case', ['boolean', ['get', 'selected'], false], '#16a34a', '#34d399'], 'fill-opacity': 0.38 } })
      map.addLayer({ id: 'properties-line', type: 'line', source: 'properties', paint: { 'line-color': ['case', ['boolean', ['get', 'selected'], false], '#14532d', '#047857'], 'line-width': ['case', ['boolean', ['get', 'selected'], false], 3, 1.5] } })
      map.addLayer({ id: 'draft-fill', type: 'fill', source: 'draft', paint: { 'fill-color': '#f59e0b', 'fill-opacity': 0.28 } })
      map.addLayer({ id: 'draft-line', type: 'line', source: 'draft', paint: { 'line-color': '#b45309', 'line-width': 3, 'line-dasharray': [2, 1] } })
      map.addLayer({ id: 'draft-progress-line', type: 'line', source: 'draft-progress', paint: { 'line-color': '#b45309', 'line-width': 3, 'line-dasharray': [1.5, 1] } })
      map.addLayer({
        id: 'draft-vertices-layer',
        type: 'circle',
        source: 'draft-vertices',
        paint: {
          'circle-radius': 6,
          'circle-color': ['case', ['==', ['get', 'ring'], 0], '#fff7ed', '#f0f9ff'],
          'circle-stroke-width': 3,
          'circle-stroke-color': ['case', ['==', ['get', 'ring'], 0], '#b45309', '#0369a1'],
        },
      })

      map.on('click', 'properties-fill', (event) => {
        if (modeRef.current !== 'browse') return
        const id = event.features?.[0]?.properties?.id as string | undefined
        const property = propertiesRef.current.find((item) => item.id === id)
        if (property) selectRef.current(property)
      })
      map.on('click', (event) => {
        if (!isDrawingMode(modeRef.current)) return
        const point = [Number(event.lngLat.lng.toFixed(7)), Number(event.lngLat.lat.toFixed(7))]
        const next = [...drawPointsRef.current, point]
        drawPointsRef.current = next
        setDrawPoints(next)
        setDrawingError('')
        if (next.length < 3) {
          draftChangeRef.current(drawBaseRef.current)
          return
        }
        try {
          draftChangeRef.current(composeDrawing(drawBaseRef.current, next, modeRef.current))
        } catch (error) {
          setDrawingError(error instanceof Error ? error.message : 'Não foi possível adicionar o anel.')
          draftChangeRef.current(drawBaseRef.current)
        }
      })
      map.on('mousedown', 'draft-vertices-layer', (event) => {
        if (modeRef.current !== 'edit') return
        const properties = event.features?.[0]?.properties
        if (!properties) return
        dragRef.current = {
          polygon: Number(properties.polygon),
          ring: Number(properties.ring),
          vertex: Number(properties.vertex),
        }
        event.originalEvent.preventDefault()
        map.dragPan.disable()
        map.getCanvas().style.cursor = 'grabbing'
      })
      map.on('mousemove', (event) => {
        if (!dragRef.current || !draftRef.current) return
        draftChangeRef.current(moveVertex(draftRef.current, dragRef.current, [Number(event.lngLat.lng.toFixed(7)), Number(event.lngLat.lat.toFixed(7))]))
      })
      map.on('mouseup', () => {
        if (!dragRef.current) return
        dragRef.current = null
        map.dragPan.enable()
        map.getCanvas().style.cursor = ''
      })
      map.on('mouseenter', 'properties-fill', () => { if (modeRef.current === 'browse') map.getCanvas().style.cursor = 'pointer' })
      map.on('mouseenter', 'draft-vertices-layer', () => { if (modeRef.current === 'edit') map.getCanvas().style.cursor = 'grab' })
      map.on('mouseleave', 'properties-fill', () => { if (!dragRef.current) map.getCanvas().style.cursor = '' })
      map.on('mouseleave', 'draft-vertices-layer', () => { if (!dragRef.current) map.getCanvas().style.cursor = '' })
      setLoaded(true)
    })
    mapRef.current = map
    return () => { map.remove(); mapRef.current = null }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    const collection = {
      type: 'FeatureCollection' as const,
      features: properties.map((property) => ({ type: 'Feature' as const, geometry: property.geometry, properties: { id: property.id, name: property.name, selected: property.id === selectedId } })),
    }
    ;(map.getSource('properties') as GeoJSONSource).setData(collection)
    const visible = selectedId ? properties.filter((property) => property.id === selectedId) : properties
    if (visible.length && !isDrawingMode(mode) && !draftGeometry) {
      const bounds = new maplibregl.LngLatBounds()
      visible.forEach((property) => extendBounds(bounds, property.geometry.coordinates))
      if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 55, maxZoom: 15, duration: 500 })
    }
  }, [draftGeometry, loaded, mode, properties, selectedId])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    ;(map.getSource('draft') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: draftGeometry ? [{ type: 'Feature', geometry: draftGeometry, properties: {} }] : [],
    })
    ;(map.getSource('draft-progress') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: isDrawingMode(mode) && drawPoints.length >= 2 ? [{ type: 'Feature', geometry: { type: 'LineString', coordinates: drawPoints }, properties: {} }] : [],
    })
    ;(map.getSource('draft-vertices') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: isDrawingMode(mode)
        ? drawPoints.map((coordinates) => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates },
          properties: { ring: mode === 'draw-hole' ? 1 : 0 },
        }))
        : geometryVertices(draftGeometry, mode),
    })
  }, [draftGeometry, drawPoints, loaded, mode])

  function updateDrawingPreview(points: number[][], drawingMode: 'draw-polygon' | 'draw-hole') {
    setDrawingError('')
    if (points.length < 3) {
      onDraftChange(drawBaseRef.current)
      return
    }
    try {
      onDraftChange(composeDrawing(drawBaseRef.current, points, drawingMode))
    } catch (error) {
      setDrawingError(error instanceof Error ? error.message : 'Não foi possível adicionar o anel.')
      onDraftChange(drawBaseRef.current)
    }
  }

  function undoPoint() {
    const next = drawPointsRef.current.slice(0, -1)
    drawPointsRef.current = next
    setDrawPoints(next)
    if (isDrawingMode(mode)) updateDrawingPreview(next, mode)
  }

  function clearDrawing() {
    drawPointsRef.current = []
    setDrawPoints([])
    setDrawingError('')
    onDraftChange(drawBaseRef.current)
    onCancelDrawing()
  }

  function finishDrawing() {
    if (!isDrawingMode(mode) || drawPoints.length < 3) return
    try {
      onDraftChange(composeDrawing(drawBaseRef.current, drawPoints, mode))
      setDrawingError('')
      onFinishEditing()
    } catch (error) {
      setDrawingError(error instanceof Error ? error.message : 'Não foi possível concluir o desenho.')
    }
  }

  return (
    <div className="relative overflow-hidden rounded-2xl">
      <div ref={containerRef} className="h-[480px] w-full" aria-label="Mapa das propriedades" />
      {isDrawingMode(mode) && (
        <div className="absolute bottom-3 left-3 right-3 flex max-w-xl flex-wrap items-center gap-2 rounded-xl border border-amber-200 bg-white/95 p-3 shadow-lg backdrop-blur sm:right-auto">
          <div className="mr-1 min-w-36">
            <p className="text-xs font-bold text-amber-900">{mode === 'draw-hole' ? 'Desenhando furo' : drawBaseRef.current ? 'Novo componente' : 'Primeiro componente'} · {drawPoints.length} pontos</p>
            {drawingError && <p className="mt-1 text-xs font-semibold text-rose-700">{drawingError}</p>}
          </div>
          <button type="button" onClick={undoPoint} disabled={!drawPoints.length} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 disabled:opacity-40">Desfazer ponto</button>
          <button type="button" onClick={clearDrawing} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700">Descartar anel</button>
          <button type="button" onClick={finishDrawing} disabled={drawPoints.length < 3 || Boolean(drawingError)} className="rounded-lg bg-amber-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-40">Concluir anel</button>
        </div>
      )}
      {mode === 'edit' && (
        <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-white/95 p-3 shadow-lg backdrop-blur sm:right-auto">
          <span className="text-xs font-semibold text-amber-900">Arraste os pontos para ajustar os limites.</span>
          <button type="button" onClick={onFinishEditing} className="shrink-0 rounded-lg bg-amber-600 px-3 py-2 text-xs font-bold text-white">Concluir edição</button>
        </div>
      )}
    </div>
  )
}
