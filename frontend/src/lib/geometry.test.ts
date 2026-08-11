import { describe, expect, it } from 'vitest'
import {
  appendHole,
  appendPolygon,
  geometryPolygons,
  moveVertex,
  removeHole,
  removePolygon,
} from './geometry'

const outer = [[0, 0], [0, 10], [10, 10], [10, 0]]

describe('edição de geometrias compostas', () => {
  it('cria um MultiPolygon ao adicionar um segundo componente', () => {
    const first = appendPolygon(null, outer)
    const result = appendPolygon(first, [[20, 20], [20, 25], [25, 25], [25, 20]])

    expect(result.type).toBe('MultiPolygon')
    expect(geometryPolygons(result)).toHaveLength(2)
  })

  it('adiciona um furo ao componente que contém o desenho', () => {
    const polygon = appendPolygon(null, outer)
    const result = appendHole(polygon, [[2, 2], [2, 4], [4, 4], [4, 2]])

    expect(geometryPolygons(result)[0]).toHaveLength(2)
  })

  it('rejeita furo fora da geometria e polígono sobreposto', () => {
    const polygon = appendPolygon(null, outer)

    expect(() => appendHole(polygon, [[12, 12], [12, 14], [14, 14], [14, 12]])).toThrow(/totalmente dentro/i)
    expect(() => appendPolygon(polygon, [[5, 5], [5, 12], [12, 12], [12, 5]])).toThrow(/sobrepor/i)
  })

  it('move vértices de furos e remove anéis ou componentes', () => {
    const withHole = appendHole(appendPolygon(null, outer), [[2, 2], [2, 4], [4, 4], [4, 2]])
    const moved = moveVertex(withHole, { polygon: 0, ring: 1, vertex: 0 }, [1, 1])
    expect(geometryPolygons(moved)[0][1][0]).toEqual([1, 1])
    expect(geometryPolygons(moved)[0][1].at(-1)).toEqual([1, 1])

    const withoutHole = removeHole(moved, 0, 1)
    expect(geometryPolygons(withoutHole)[0]).toHaveLength(1)
    expect(removePolygon(withoutHole, 0)).toBeNull()
  })
})
