# Mapas gerados

## Composição cartográfica

`render_index_map` recebe o array NDVI, a máscara válida e os metadados espaciais da grade. O
template atual produz uma folha A4 paisagem com:

- raster NDVI em classes de -1 a 1;
- limite da AOI;
- legenda e escala de cores;
- grade com rótulos de longitude/latitude;
- escala gráfica e indicação de norte;
- nome e área da propriedade;
- data, satélite, nuvens e estatísticas NDVI;
- fonte Copernicus, STAC item e identificação Delta Mapas.

A grade permanece na projeção UTM escolhida para o processamento. PyProj transforma somente os
rótulos dos eixos para coordenadas geográficas. Matplotlib foi preferido sem Cartopy nesta primeira
versão para reduzir dependências no alvo ARM64 e evitar downloads de mapas-base em runtime.

Rasters maiores que `MAP_RENDER_MAX_DIMENSION_PIXELS` são reduzidos apenas para apresentação. O
cálculo e as estatísticas continuam usando todos os pixels válidos. PNG e PDF são gerados dentro do
mesmo `TemporaryDirectory` dos intermediários.

## Persistência e cobrança

O serviço de produto envia `map.png` e `map.pdf` pelo storage padrão do Django. As chaves seguem:

```text
tenants/{tenant_id}/maps/{ano}/{mes}/{generated_map_id}/map.png
tenants/{tenant_id}/maps/{ano}/{mes}/{generated_map_id}/map.pdf
```

O bucket permanece privado. Depois dos dois uploads, uma transação bloqueia o `MapJob`, cria um único
`GeneratedMap`, captura a reserva e muda o job para `COMPLETED`. Retries encontram o produto
existente e não duplicam o mapa nem a captura. Exceções comuns removem uploads parciais e liberam o
crédito; uma rotina futura de reconciliação ainda deverá tratar interrupções abruptas do processo
entre storage e banco.

A finalização trava novamente o job e rejeita `CANCELLED` antes de persistir ou capturar. Arquivos
que tenham sido enviados durante a corrida são removidos pelo fluxo de compensação.

## Interface autenticada

```text
GET /maps/
GET /maps/?search=Fazenda&ordering=-scene_date
GET /maps/{uuid}/png/
GET /maps/{uuid}/pdf/
```

A listagem aceita `search` por propriedade ou identificador STAC, `ordering` por `created_at`,
`scene_date` ou `cloud_cover`, além de paginação.

Listagem e download exigem sessão e membership ativa no tenant resolvido. Os arquivos são servidos
pela aplicação; a URL interna do MinIO e suas credenciais não são expostas.
