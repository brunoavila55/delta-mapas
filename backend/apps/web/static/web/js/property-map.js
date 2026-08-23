(() => {
  const container = document.getElementById('property-map')
  if (!container || typeof L === 'undefined') return

  const geometryField = document.getElementById('id_geometry')
  const dataEl = document.getElementById('property-map-data')
  let initialData = {}
  try {
    initialData = dataEl ? JSON.parse(dataEl.textContent) : {}
  } catch (error) {
    initialData = {}
  }

  const map = L.map(container, { center: [-15.8, -47.9], zoom: 4 })

  const satellite = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    { maxZoom: 19, attribution: 'Esri, Maxar, Earthstar Geographics' },
  )
  const streets = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  })
  satellite.addTo(map)
  L.control.layers({ Satélite: satellite, Ruas: streets }, null, { position: 'topright' }).addTo(map)

  const drawnItems = new L.FeatureGroup().addTo(map)

  map.pm.setGlobalOptions({ layerGroup: drawnItems, allowSelfIntersection: false })
  map.pm.addControls({
    position: 'topleft',
    drawMarker: false,
    drawCircleMarker: false,
    drawPolyline: false,
    drawRectangle: false,
    drawCircle: false,
    drawText: false,
    drawPolygon: true,
    editMode: true,
    dragMode: true,
    cutPolygon: true,
    removalMode: true,
    rotateMode: false,
  })

  function syncGeometry() {
    if (!geometryField) return
    const geometries = drawnItems
      .getLayers()
      .map((layer) => (layer.toGeoJSON ? layer.toGeoJSON().geometry : null))
      .filter((geometry) => geometry && geometry.type === 'Polygon')

    if (!geometries.length) {
      geometryField.value = ''
      return
    }
    if (geometries.length === 1) {
      geometryField.value = JSON.stringify(geometries[0])
      return
    }
    geometryField.value = JSON.stringify({
      type: 'MultiPolygon',
      coordinates: geometries.map((geometry) => geometry.coordinates),
    })
  }

  map.on(
    'pm:create pm:remove pm:cut pm:update pm:markerdragend pm:vertexadded pm:vertexremoved pm:dragend pm:rotateend',
    syncGeometry,
  )

  function loadExistingGeometry(geometry) {
    if (!geometry) return
    const parts =
      geometry.type === 'MultiPolygon'
        ? geometry.coordinates.map((coordinates) => ({ type: 'Polygon', coordinates }))
        : [geometry]

    parts.forEach((part) => {
      const layers = L.geoJSON(part).getLayers()
      if (layers[0]) drawnItems.addLayer(layers[0])
    })

    if (drawnItems.getLayers().length) {
      map.fitBounds(drawnItems.getBounds(), { padding: [30, 30] })
    }
  }

  loadExistingGeometry(initialData.geometry)
  if (!drawnItems.getLayers().length) {
    map.setView([-15.8, -47.9], 4)
  }

  const searchInput = document.getElementById('property-map-search')
  const searchResults = document.getElementById('property-map-search-results')
  if (searchInput && searchResults) {
    let searchTimer = null
    let activeRequest = 0

    function clearResults() {
      searchResults.innerHTML = ''
      searchResults.hidden = true
    }

    searchInput.addEventListener('input', () => {
      window.clearTimeout(searchTimer)
      const query = searchInput.value.trim()
      clearResults()
      if (query.length < 3) return

      searchTimer = window.setTimeout(async () => {
        const requestId = ++activeRequest
        try {
          const url =
            'https://nominatim.openstreetmap.org/search?format=json&limit=6&q=' +
            encodeURIComponent(query)
          const response = await fetch(url, { headers: { Accept: 'application/json' } })
          if (!response.ok || requestId !== activeRequest) return
          const results = await response.json()
          if (requestId !== activeRequest) return
          clearResults()
          if (!results.length) return
          results.forEach((result) => {
            const item = document.createElement('button')
            item.type = 'button'
            item.className = 'geo-search-item'
            item.textContent = result.display_name
            item.addEventListener('click', () => {
              map.setView([Number(result.lat), Number(result.lon)], 15)
              searchInput.value = result.display_name
              clearResults()
            })
            searchResults.appendChild(item)
          })
          searchResults.hidden = false
        } catch (error) {
          clearResults()
        }
      }, 400)
    })

    document.addEventListener('click', (event) => {
      if (!searchResults.contains(event.target) && event.target !== searchInput) {
        clearResults()
      }
    })
  }

  window.setTimeout(() => map.invalidateSize(), 150)
})()
