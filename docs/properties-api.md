# API de autenticação e propriedades

Todos os endpoints usam o prefixo `/api/v1/` e, exceto login/refresh, exigem um access token JWT no
header `Authorization: Bearer <token>`. O hostname seleciona o tenant antes da autenticação; um token
global não concede acesso sem uma `Membership` ativa na organização solicitada.

## Autenticação

### Login

```http
POST /api/v1/auth/login/
Content-Type: application/json

{
  "username": "admin",
  "password": "senha"
}
```

A resposta contém `access`, `refresh`, dados do usuário e o tenant atual. O access token expira em 15
minutos por padrão.

### Refresh, usuário atual e logout

```text
POST /api/v1/auth/refresh/
GET  /api/v1/auth/me/
POST /api/v1/auth/logout/
```

O logout recebe `{"refresh": "..."}` e adiciona o refresh token à blacklist. Rotação e blacklist
também são aplicadas no refresh.

## Propriedades

```text
GET    /api/v1/properties/
POST   /api/v1/properties/
GET    /api/v1/properties/{uuid}/
PATCH  /api/v1/properties/{uuid}/
DELETE /api/v1/properties/{uuid}/
POST   /api/v1/properties/import/
```

As listagens são paginadas. `search` consulta nome, município e estado; `ordering` aceita `name`,
`area_hectares`, `created_at` e `updated_at`.

Exemplo de criação por GeoJSON:

```json
{
  "name": "Fazenda Delta",
  "description": "Talhão principal",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-48.01, -15.01],
      [-48.01, -15.00],
      [-48.00, -15.00],
      [-48.00, -15.01],
      [-48.01, -15.01]
    ]]
  },
  "city": "Brasília",
  "state": "DF",
  "country": "BR"
}
```

O backend transforma `Polygon` em `MultiPolygon`, tenta corrigir auto-interseções quando o resultado
continua poligonal, rejeita coordenadas fora do EPSG:4326 e sempre recalcula `area_hectares` em uma
projeção equal-area. O valor de área enviado pelo cliente é ignorado.

## Importação de shapefile

O endpoint de importação usa `multipart/form-data` com os campos `file`, `name` e os metadados
opcionais da propriedade. O ZIP deve possuir exatamente um dataset e, para o mesmo nome-base:

```text
.shp .shx .dbf .prj
```

O arquivo é copiado por streaming para `TemporaryDirectory`, validado e extraído manualmente. São
rejeitados caminhos absolutos, `..`, symlinks, arquivos criptografados, extensões desconhecidas,
ZIPs com expansão excessiva e arquivos acima dos limites configurados. GeoPandas lê apenas a
geometria, exige CRS, transforma para EPSG:4326 e une as feições poligonais. Nenhum componente do
shapefile é persistido.

## Autorização e isolamento

- `OWNER`, `ADMIN`, `AGRONOMIST` e `MEMBER`: leitura e escrita;
- `VIEWER`: somente leitura;
- usuário sem membership ativa: `403`;
- UUID existente em outro schema: `404` sem revelar a existência do recurso.
