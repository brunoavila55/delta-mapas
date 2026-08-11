# Pesquisa STAC e núcleo de índices

## Escopo implementado

`CopernicusSceneService` isola o `pystac-client` do restante da aplicação. A consulta usa:

- collection `sentinel-2-l2a`;
- geometria do snapshot como `intersects`;
- dia UTC completo ou intervalo UTC completo;
- limite `eo:cloud_cover`;
- quantidade máxima configurável de itens.

Os resultados ainda são validados localmente. Uma cena só é elegível se possuir data, cobertura de
nuvens válida e assets para os aliases lógicos `B04`, `B08` e `SCL`. No catálogo atual, as
preferências são `B04_10m`, `B08_10m` e `SCL_20m`, com aliases simples como fallback.

A mesma ordenação é enviada ao servidor e reaplicada localmente de forma determinística:

1. menor `eo:cloud_cover`;
2. cena mais recente;
3. ID do item em ordem crescente para desempate final.

## Configuração

```text
COPERNICUS_STAC_URL=https://stac.dataspace.copernicus.eu/v1/
COPERNICUS_STAC_COLLECTION=sentinel-2-l2a
COPERNICUS_STAC_TIMEOUT_SECONDS=30
COPERNICUS_STAC_MAX_ITEMS=100
COPERNICUS_STAC_MAX_RETRIES=2
COPERNICUS_STAC_RETRY_DELAY_SECONDS=15
```

Timeouts/erros do catálogo são traduzidos para exceção de domínio. O Celery faz retries limitados;
ausência de cena é erro definitivo e não recebe retry.

## Processadores

`BaseIndexProcessor` define o contrato de entrada por bandas e retorna `IndexProcessingResult`, com
array `float32`, máscara booleana e metadados. O registro atual associa `NDVI` a `NDVIProcessor`,
permitindo incluir novos índices sem alterar a task.

O `NDVIProcessor` espera arrays 2D já alinhados:

```text
B04 = vermelho
B08 = infravermelho próximo
SCL = classificação da cena
```

O cálculo `(B08 - B04) / (B08 + B04)` é vetorizado com NumPy. O processador mascara nodata,
masked arrays, valores não finitos, denominador zero e, por padrão, as classes SCL
`0, 1, 3, 8, 9, 10, 11`. A lista pode ser substituída ao instanciar o processador.

## Obtenção e processamento raster

O STAC continua responsável pela descoberta e rastreabilidade. Após selecionar a cena, o worker usa
OAuth2 Client Credentials para obter um token de curta duração e chama a Sentinel Hub Process API.
O token permanece em memória, é reutilizado enquanto válido e renovado antes da expiração.

A requisição restringe o intervalo a cinco minutos antes/depois do horário da cena STAC e solicita
B04, B08, SCL e `dataMask` em um único GeoTIFF `FLOAT32`. A AOI é transformada para a zona UTM do
centroide e processada numa grade comum de 10 metros. O `dataMask` remove pixels fora da AOI; SCL,
nodata e valores inválidos são aplicados pelo pipeline NDVI.

O download é streaming, possui limites configuráveis de pixels e bytes e usa arquivo `.part` com
rename atômico. Tudo fica em `TemporaryDirectory()` e é removido mesmo em falha; nenhum raster
Sentinel bruto é persistido no MinIO.

As credenciais existirão apenas no `.env` e serão disponibilizadas somente ao backend e ao worker:

```text
COPERNICUS_CLIENT_ID=
COPERNICUS_CLIENT_SECRET=
COPERNICUS_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
COPERNICUS_PROCESS_URL=https://sh.dataspace.copernicus.eu/process/v1
```

Backend e worker são os únicos consumidores dessas variáveis. Falhas temporárias de autenticação,
rede, rate limit e servidor recebem retry limitado; credenciais recusadas, payload inválido e limites
excedidos encerram o job sem retry e liberam a reserva.
