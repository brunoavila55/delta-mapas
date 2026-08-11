import type { Geometry } from './types'

export type Position = [number, number]
export type VertexAddress = { polygon: number; ring: number; vertex: number }

export function geometryPolygons(geometry: Geometry): number[][][][] {
  return geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
}

function cloneGeometry(geometry: Geometry): Geometry {
  return structuredClone(geometry)
}

export function closeRing(points: number[][]): number[][] {
  if (points.length < 3) throw new Error('O anel precisa de pelo menos três pontos.')
  const ring = points.map((point) => [point[0], point[1]])
  const first = ring[0]
  const last = ring[ring.length - 1]
  if (first[0] !== last[0] || first[1] !== last[1]) ring.push([...first])
  return ring
}

function orientation(a: number[], b: number[], c: number[]): number {
  return (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
}

function pointOnSegment(point: number[], a: number[], b: number[]): boolean {
  const cross = (point[1] - a[1]) * (b[0] - a[0]) - (point[0] - a[0]) * (b[1] - a[1])
  if (Math.abs(cross) > 1e-10) return false
  return point[0] >= Math.min(a[0], b[0]) && point[0] <= Math.max(a[0], b[0])
    && point[1] >= Math.min(a[1], b[1]) && point[1] <= Math.max(a[1], b[1])
}

function segmentsIntersect(a: number[], b: number[], c: number[], d: number[]): boolean {
  const o1 = orientation(a, b, c)
  const o2 = orientation(a, b, d)
  const o3 = orientation(c, d, a)
  const o4 = orientation(c, d, b)
  if (o1 === 0 && pointOnSegment(c, a, b)) return true
  if (o2 === 0 && pointOnSegment(d, a, b)) return true
  if (o3 === 0 && pointOnSegment(a, c, d)) return true
  if (o4 === 0 && pointOnSegment(b, c, d)) return true
  return (o1 > 0) !== (o2 > 0) && (o3 > 0) !== (o4 > 0)
}

function ringsIntersect(first: number[][], second: number[][]): boolean {
  for (let firstIndex = 0; firstIndex < first.length - 1; firstIndex += 1) {
    for (let secondIndex = 0; secondIndex < second.length - 1; secondIndex += 1) {
      if (segmentsIntersect(
        first[firstIndex],
        first[firstIndex + 1],
        second[secondIndex],
        second[secondIndex + 1],
      )) return true
    }
  }
  return false
}

export function pointInRing(point: number[], ring: number[][]): boolean {
  let inside = false
  for (let current = 0, previous = ring.length - 1; current < ring.length; previous = current, current += 1) {
    const a = ring[current]
    const b = ring[previous]
    if (pointOnSegment(point, a, b)) return false
    const crossesLatitude = (a[1] > point[1]) !== (b[1] > point[1])
    const crossingLongitude = ((b[0] - a[0]) * (point[1] - a[1])) / (b[1] - a[1]) + a[0]
    if (crossesLatitude && point[0] < crossingLongitude) inside = !inside
  }
  return inside
}

function pointInPolygon(point: number[], polygon: number[][][]): boolean {
  return pointInRing(point, polygon[0])
    && !polygon.slice(1).some((hole) => pointInRing(point, hole))
}

export function appendPolygon(geometry: Geometry | null, points: number[][]): Geometry {
  const ring = closeRing(points)
  if (!geometry) return { type: 'Polygon', coordinates: [ring] }

  for (const polygon of geometryPolygons(geometry)) {
    if (polygon.some((existingRing) => ringsIntersect(ring, existingRing))
      || pointInPolygon(ring[0], polygon)
      || pointInRing(polygon[0][0], ring)) {
      throw new Error('O novo polígono não pode sobrepor uma área existente.')
    }
  }

  const newPolygon = [ring]
  if (geometry.type === 'Polygon') {
    return { type: 'MultiPolygon', coordinates: [structuredClone(geometry.coordinates), newPolygon] }
  }
  return { type: 'MultiPolygon', coordinates: [...structuredClone(geometry.coordinates), newPolygon] }
}

export function appendHole(geometry: Geometry | null, points: number[][]): Geometry {
  if (!geometry) throw new Error('Desenhe um polígono antes de adicionar um furo.')
  const ring = closeRing(points)
  const updated = cloneGeometry(geometry)
  const polygons = geometryPolygons(updated)
  const target = polygons.find((polygon) => {
    const exterior = polygon[0]
    if (!ring.slice(0, -1).every((point) => pointInRing(point, exterior))) return false
    if (ringsIntersect(ring, exterior)) return false
    return polygon.slice(1).every((hole) => (
      !ringsIntersect(ring, hole)
      && !pointInRing(ring[0], hole)
      && !pointInRing(hole[0], ring)
    ))
  })
  if (!target) {
    throw new Error('O furo deve ficar totalmente dentro de um componente e não pode cruzar outro anel.')
  }
  target.push(ring)
  return updated
}

export function removePolygon(geometry: Geometry, polygonIndex: number): Geometry | null {
  const polygons = structuredClone(geometryPolygons(geometry))
  polygons.splice(polygonIndex, 1)
  if (!polygons.length) return null
  if (polygons.length === 1) return { type: 'Polygon', coordinates: polygons[0] }
  return { type: 'MultiPolygon', coordinates: polygons }
}

export function removeHole(geometry: Geometry, polygonIndex: number, ringIndex: number): Geometry {
  if (ringIndex < 1) return geometry
  const updated = cloneGeometry(geometry)
  geometryPolygons(updated)[polygonIndex]?.splice(ringIndex, 1)
  return updated
}

export function moveVertex(geometry: Geometry, address: VertexAddress, coordinates: Position): Geometry {
  const updated = cloneGeometry(geometry)
  const ring = geometryPolygons(updated)[address.polygon]?.[address.ring]
  if (!ring?.[address.vertex]) return geometry
  ring[address.vertex] = coordinates
  if (address.vertex === 0) ring[ring.length - 1] = [...coordinates]
  return updated
}
