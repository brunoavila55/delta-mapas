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

## Limite desta etapa

Nenhum asset é obtido ou persistido. Foi decidido usar OAuth2 Client Credentials e a Sentinel Hub
Process API na próxima etapa, em vez de credenciais permanentes para acesso direto ao bucket S3
`eodata`. O STAC continuará responsável pela descoberta e rastreabilidade da cena.

O próximo estágio deverá usar `tempfile.TemporaryDirectory()` e Rasterio para:

1. obter e reutilizar com segurança um token OAuth de curta duração;
2. solicitar somente B04, B08 e SCL já limitados à AOI;
3. reprojetar/alinhá-los numa grade comum, quando necessário;
4. entregar os arrays ao processador;
5. remover todos os intermediários mesmo em falha.

As credenciais existirão apenas no `.env` e serão disponibilizadas somente ao backend e ao worker:

```text
COPERNICUS_CLIENT_ID=
COPERNICUS_CLIENT_SECRET=
COPERNICUS_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
COPERNICUS_PROCESS_URL=https://sh.dataspace.copernicus.eu/api/v1/process
```
